import tkinter as tk
from tkinter import messagebox, filedialog
import win32serviceutil
import win32service
import psutil
import os
import json
import threading
import queue
import time
import pystray
from PIL import Image, ImageDraw
import sys
import re
import tkinter.ttk as ttk

class ServiceManagerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Wish3DEarth服务管理工具")
        self.root.geometry("900x600")  # 增加窗口大小
        
        # 设置窗口图标
        self.create_app_icon()
        
        # 处理窗口关闭事件
        self.root.protocol('WM_DELETE_WINDOW', self.hide_window)
        
        # 定义主题颜色
        self.colors = {
            'bg': "#f5f6fa",            # 主背景色
            'menu_bg': "#2c3e50",       # 菜单背景色
            'menu_hover': "#34495e",    # 菜单悬停色
            'accent': "#3498db",        # 强调色
            'success': "#2ecc71",       # 成功色
            'warning': "#f1c40f",       # 警告色
            'error': "#e74c3c",         # 错误色
            'text': "#2c3e50",          # 文本色
            'text_light': "#ecf0f1"     # 浅色文本
        }
        
        # 设置主窗口背景色
        self.root.configure(bg=self.colors['bg'])
        
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
        
        self.status_labels = {}
        self.middleware_status_labels = {}
        
        # 用于线程间通信的队列
        self.status_queue = queue.Queue()
        
        # 添加进程状态缓存
        self.process_cache = {}
        self.last_check_time = 0
        self.CHECK_INTERVAL = 10
        
        # 操作锁，防止并发操作导致的问题
        self.operation_lock = threading.Lock()
        
        # 初始化运行状态标志
        self.is_running = True
        
        # 状态更新线程
        self.status_thread = threading.Thread(target=self.background_status_check, daemon=True)
        self.status_thread.start()
        
        # 创建主布局
        self.create_layout()
        
        # 初始化UI
        self.show_service_tab()
        self.update_status()
        
    def create_app_icon(self):
        """创建应用图标"""
        # 创建一个更漂亮的图标
        icon_size = 64
        image = Image.new('RGBA', (icon_size, icon_size), color=(0,0,0,0))
        dc = ImageDraw.Draw(image)
        
        # 绘制渐变背景
        for y in range(icon_size):
            for x in range(icon_size):
                # 计算到中心的距离
                distance = ((x - icon_size/2)**2 + (y - icon_size/2)**2)**0.5
                # 创建渐变效果
                alpha = max(0, min(255, int(255 * (1 - distance/32))))
                dc.point((x, y), fill=(52, 152, 219, alpha))  # 使用蓝色
        
        # 绘制边框
        margin = 2
        dc.ellipse([margin, margin, icon_size-margin, icon_size-margin],
                  outline=(41, 128, 185, 255), width=2)
        
        # 保存图标供后续使用
        self.icon_image = image
        
    def setup_tray(self):
        """设置系统托盘"""
        menu = (
            pystray.MenuItem("显示主窗口", self.show_window),
            pystray.MenuItem("退出", self.quit_app)
        )
        
        self.tray_icon = pystray.Icon(
            "service_manager",
            self.icon_image,
            "Wish3DEarth服务管理工具",
            menu
        )
        
        # 启动托盘图标
        self.tray_icon.run_detached()
        
    def show_window(self, icon=None, item=None):
        """显示主窗口"""
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()
        
    def hide_window(self):
        """隐藏主窗口"""
        self.root.withdraw()
        
    def quit_app(self, icon=None, item=None):
        """退出应用程序"""
        self.is_running = False
        if hasattr(self, 'tray_icon'):
            self.tray_icon.stop()
        self.root.quit()
        
    def create_layout(self):
        """创建主布局"""
        # 创建左侧菜单栏
        self.menu_frame = tk.Frame(self.root, bg=self.colors['menu_bg'], width=200)
        self.menu_frame.pack(side=tk.LEFT, fill=tk.Y)
        self.menu_frame.pack_propagate(False)  # 固定宽度
        
        # 创建logo区域
        logo_frame = tk.Frame(self.menu_frame, bg=self.colors['menu_bg'], height=100)
        logo_frame.pack(fill=tk.X, pady=(20,30))
        logo_frame.pack_propagate(False)
        
        # 添加标题
        tk.Label(logo_frame, text="服务管理工具", 
                font=("Microsoft YaHei UI", 16, "bold"),
                fg=self.colors['text_light'],
                bg=self.colors['menu_bg']).pack(pady=20)
        
        # 创建菜单按钮
        self.create_menu_button("数据库管理", self.show_service_tab, "database")
        self.create_menu_button("中间件管理", self.show_middleware_tab, "server")
        self.create_menu_button("Java进程管理", self.show_java_tab, "coffee")
        
        # 添加版本信息
        version_frame = tk.Frame(self.menu_frame, bg=self.colors['menu_bg'])
        version_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=10)
        
        tk.Label(version_frame, 
                text="Version 1.0.0", 
                font=("Microsoft YaHei UI", 8),
                fg=self.colors['text_light'],
                bg=self.colors['menu_bg']).pack(side=tk.LEFT, padx=10)
        
        # 创建主内容区域
        self.content_frame = tk.Frame(self.root, bg=self.colors['bg'])
        self.content_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        
        # 创建各个标签页
        self.service_tab = tk.Frame(self.content_frame, bg=self.colors['bg'])
        self.middleware_tab = tk.Frame(self.content_frame, bg=self.colors['bg'])
        self.java_tab = tk.Frame(self.content_frame, bg=self.colors['bg'])
        
        # 初始化各个标签页
        self.create_service_tab()
        self.create_middleware_tab()
        self.create_java_tab()
        
    def create_menu_button(self, text, command, icon_name=None):
        """创建菜单按钮"""
        frame = tk.Frame(self.menu_frame, bg=self.colors['menu_bg'])
        frame.pack(fill=tk.X, pady=2)
        
        # 创建按钮
        btn = tk.Button(frame, 
                       text=f" {text}",
                       font=("Microsoft YaHei UI", 11),
                       fg=self.colors['text_light'],
                       bg=self.colors['menu_bg'],
                       bd=0,
                       relief=tk.FLAT,
                       activebackground=self.colors['menu_hover'],
                       activeforeground=self.colors['text_light'],
                       command=command)
        btn.pack(fill=tk.X, ipady=10, padx=5)
        
        # 添加鼠标悬停效果
        def on_enter(e):
            btn['bg'] = self.colors['menu_hover']
        def on_leave(e):
            btn['bg'] = self.colors['menu_bg']
            
        btn.bind("<Enter>", on_enter)
        btn.bind("<Leave>", on_leave)

    def create_service_tab(self):
        """创建服务管理标签页"""
        # 创建标题
        title_frame = tk.Frame(self.service_tab, bg=self.colors['bg'])
        title_frame.pack(fill=tk.X, padx=20, pady=(20,10))
        
        tk.Label(title_frame, 
                text="数据库服务管理",
                font=("Microsoft YaHei UI", 16, "bold"),
                fg=self.colors['text'],
                bg=self.colors['bg']).pack(anchor=tk.W)
                
        # 创建服务列表容器
        services_frame = tk.Frame(self.service_tab, bg=self.colors['bg'])
        services_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
        
        for service_name in self.services:
            # 创建服务卡片
            card = tk.Frame(services_frame, bg="white", bd=0)
            card.pack(fill=tk.X, pady=10)
            
            # 添加圆角和阴影效果（通过内部框架实现）
            inner_frame = tk.Frame(card, bg="white", bd=1, relief=tk.SOLID)
            inner_frame.pack(fill=tk.BOTH, padx=2, pady=2)
            
            # 左侧信息区域
            info_frame = tk.Frame(inner_frame, bg="white")
            info_frame.pack(side=tk.LEFT, fill=tk.BOTH, padx=20, pady=15)
            
            # 服务名称
            tk.Label(info_frame,
                    text=service_name,
                    font=("Microsoft YaHei UI", 12, "bold"),
                    fg=self.colors['text'],
                    bg="white").pack(anchor=tk.W)
            
            # 状态标签
            status_label = tk.Label(info_frame,
                                  text="检查中...",
                                  font=("Microsoft YaHei UI", 10),
                                  fg=self.colors['text'],
                                  bg="white")
            status_label.pack(anchor=tk.W, pady=(5,0))
            self.status_labels[service_name] = status_label

            # 右侧按钮区域
            btn_frame = tk.Frame(inner_frame, bg="white")
            btn_frame.pack(side=tk.RIGHT, fill=tk.Y, padx=20, pady=15)
            
            # 创建按钮
            self.create_control_button(btn_frame, "启动",
                                    lambda sn=service_name: self.start_service(sn),
                                    self.colors['success'])
            
            self.create_control_button(btn_frame, "停止",
                                    lambda sn=service_name: self.stop_service(sn),
                                    self.colors['error'])
            
            self.create_control_button(btn_frame, "重启",
                                    lambda sn=service_name: self.restart_service(sn),
                                    self.colors['warning'])
            
            # 添加鼠标悬停效果
            def on_enter(e, frame=inner_frame):
                frame.configure(bg=self.colors['bg'])
            def on_leave(e, frame=inner_frame):
                frame.configure(bg="white")
            
            inner_frame.bind("<Enter>", on_enter)
            inner_frame.bind("<Leave>", on_leave)
            
    def create_control_button(self, parent, text, command, color):
        """创建控制按钮"""
        btn = tk.Button(parent,
                       text=text,
                       font=("Microsoft YaHei UI", 10),
                       fg="white",
                       bg=color,
                       bd=0,
                       width=8,  # 固定宽度
                       padx=5,
                       pady=3,
                       relief=tk.FLAT,
                       cursor="hand2",  # 添加手型光标
                       command=command)
        btn.pack(side=tk.LEFT, padx=5)
        
        # 添加鼠标悬停效果
        def on_enter(e):
            btn['bg'] = self.adjust_color(color, -20)
        def on_leave(e):
            btn['bg'] = color
            
        btn.bind("<Enter>", on_enter)
        btn.bind("<Leave>", on_leave)
        
        return btn

    def create_middleware_tab(self):
        """创建中间件管理标签页"""
        # 创建标题
        title_frame = tk.Frame(self.middleware_tab, bg=self.colors['bg'])
        title_frame.pack(fill=tk.X, padx=20, pady=(20,10))
        
        title_label = tk.Label(title_frame, 
                             text="中间件管理",
                             font=("Microsoft YaHei UI", 16, "bold"),
                             fg=self.colors['text'],
                             bg=self.colors['bg'])
        title_label.pack(side=tk.LEFT)
        
        # 添加新中间件按钮
        add_btn = tk.Button(title_frame,
                          text="添加中间件",
                          font=("Microsoft YaHei UI", 10),
                          fg="white",
                          bg=self.colors['accent'],
                          bd=0,
                          padx=15,
                          pady=5,
                          relief=tk.FLAT,
                          cursor="hand2",
                          command=self.add_new_middleware)
        add_btn.pack(side=tk.RIGHT)
        
        # 创建中间件列表容器
        middlewares_frame = tk.Frame(self.middleware_tab, bg=self.colors['bg'])
        middlewares_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
        
        for middleware_name, middleware_info in self.middlewares.items():
            # 创建中间件卡片
            card = tk.Frame(middlewares_frame, bg="white", bd=0)
            card.pack(fill=tk.X, pady=10)
            
            # 添加圆角和阴影效果
            inner_frame = tk.Frame(card, bg="white", bd=1, relief=tk.SOLID)
            inner_frame.pack(fill=tk.BOTH, padx=2, pady=2)
            
            # 左侧信息区域
            info_frame = tk.Frame(inner_frame, bg="white")
            info_frame.pack(side=tk.LEFT, fill=tk.BOTH, padx=20, pady=15)
            
            # 中间件名称
            tk.Label(info_frame,
                    text=middleware_name,
                    font=("Microsoft YaHei UI", 12, "bold"),
                    fg=self.colors['text'],
                    bg="white").pack(anchor=tk.W)
            
            # 进程名称
            tk.Label(info_frame,
                    text=f"进程: {middleware_info['process_name']}",
                    font=("Microsoft YaHei UI", 9),
                    fg="gray",
                    bg="white").pack(anchor=tk.W, pady=(2,5))
            
            # 状态标签
            status_label = tk.Label(info_frame,
                                  text="检查中...",
                                  font=("Microsoft YaHei UI", 10),
                                  fg=self.colors['text'],
                                  bg="white")
            status_label.pack(anchor=tk.W)
            middleware_info["status_label"] = status_label

            # 右侧按钮区域
            btn_frame = tk.Frame(inner_frame, bg="white")
            btn_frame.pack(side=tk.RIGHT, fill=tk.Y, padx=20, pady=15)
            
            # 如果是nginx，添加端口号显示和修改功能，以及代理配置功能
            if middleware_name.lower().startswith("nginx"):
                # 端口号显示区域
                port_frame = tk.Frame(info_frame, bg="white")
                port_frame.pack(anchor=tk.W, pady=(5,0), fill=tk.X)
                
                # 端口号标签
                port_label = tk.Label(port_frame,
                                    text="端口号: ",
                                    font=("Microsoft YaHei UI", 9),
                                    fg=self.colors['text'],
                                    bg="white")
                port_label.pack(side=tk.LEFT)
                
                # 当前端口号显示
                current_port_label = tk.Label(port_frame,
                                            text="未设置",
                                            font=("Microsoft YaHei UI", 9),
                                            fg=self.colors['text'],
                                            bg="white")
                current_port_label.pack(side=tk.LEFT)
                
                def modify_port():
                    # 创建对话框
                    dialog = tk.Toplevel(self.root)
                    dialog.title("修改端口号")
                    dialog.geometry("300x150")
                    dialog.configure(bg="#f0f0f0")
                    
                    # 使对话框成为模态
                    dialog.transient(self.root)
                    dialog.grab_set()
                    
                    # 创建表单框架
                    form_frame = tk.Frame(dialog, bg="#f0f0f0")
                    form_frame.pack(pady=20, padx=20, fill=tk.X)
                    
                    # 端口号输入
                    tk.Label(form_frame, text="新端口号:", bg="#f0f0f0").pack(anchor=tk.W)
                    port_var = tk.StringVar()
                    port_entry = tk.Entry(form_frame, textvariable=port_var, width=20)
                    port_entry.pack(fill=tk.X, pady=(5,20))
                    
                    # 设置当前端口号
                    work_dir = middleware_info.get("work_dir", "")
                    if work_dir:
                        nginx_conf = os.path.join(work_dir, "conf", "nginx.conf")
                        if os.path.exists(nginx_conf):
                            current_port = self.get_nginx_port(nginx_conf)
                            if current_port:
                                port_var.set(current_port)
                    
                    def submit():
                        work_dir = middleware_info.get("work_dir", "")
                        if not work_dir:
                            messagebox.showwarning("警告", "请先设置nginx的工作目录")
                            return
                        
                        nginx_conf = os.path.join(work_dir, "conf", "nginx.conf")
                        if not os.path.exists(nginx_conf):
                            messagebox.showwarning("警告", "未找到nginx配置文件")
                            return
                        
                        new_port = port_var.get().strip()
                        if not new_port.isdigit():
                            messagebox.showwarning("警告", "请输入有效的端口号")
                            return
                        
                        if self.update_nginx_port(nginx_conf, new_port):
                            middleware_info["port"] = new_port
                            self.save_middlewares()
                            # 自动重载nginx
                            self.reload_middleware(middleware_name)
                            # 更新显示的端口号
                            current_port_label.config(text=new_port)
                            # 显示成功消息
                            messagebox.showinfo("成功", "端口号已更新并重载nginx")
                            dialog.destroy()
                    
                    # 按钮区域
                    button_frame = tk.Frame(dialog, bg="#f0f0f0")
                    button_frame.pack(pady=10)
                    
                    submit_btn = tk.Button(button_frame, text="确定", command=submit,
                                         bg="#2196F3", fg="white", width=10)
                    submit_btn.pack(side=tk.LEFT, padx=5)
                    
                    cancel_btn = tk.Button(button_frame, text="取消", command=dialog.destroy,
                                         bg="#9E9E9E", fg="white", width=10)
                    cancel_btn.pack(side=tk.LEFT, padx=5)
                    
                    # 设置对话框位置为屏幕中心
                    dialog.update_idletasks()
                    width = dialog.winfo_width()
                    height = dialog.winfo_height()
                    x = (dialog.winfo_screenwidth() // 2) - (width // 2)
                    y = (dialog.winfo_screenheight() // 2) - (height // 2)
                    dialog.geometry(f"{width}x{height}+{x}+{y}")
                
                # 读取并显示当前端口号
                work_dir = middleware_info.get("work_dir", "")
                if work_dir:
                    nginx_conf = os.path.join(work_dir, "conf", "nginx.conf")
                    if os.path.exists(nginx_conf):
                        current_port = self.get_nginx_port(nginx_conf)
                        if current_port:
                            current_port_label.config(text=current_port)
                            middleware_info["port"] = current_port
                            self.save_middlewares()
            
            # 修改端口按钮
            update_btn = tk.Button(btn_frame,
                                 text="修改端口",
                                 font=("Microsoft YaHei UI", 9),
                                 fg="white",
                                 bg=self.colors['accent'],
                                 bd=0,
                                 width=8,
                                 padx=5,
                                 pady=3,
                                 relief=tk.FLAT,
                                 cursor="hand2",
                                 command=modify_port)
            update_btn.pack(side=tk.LEFT, padx=5)
            
            # 添加代理配置按钮
            proxy_btn = tk.Button(btn_frame,
                                text="添加代理",
                                font=("Microsoft YaHei UI", 9),
                                fg="white",
                                bg=self.colors['accent'],
                                bd=0,
                                width=8,
                                padx=5,
                                pady=3,
                                relief=tk.FLAT,
                                cursor="hand2",
                                command=lambda m=middleware_info: self.add_proxy_config(m))
            proxy_btn.pack(side=tk.LEFT, padx=5)
            
            # 添加查看代理按钮
            view_proxy_btn = tk.Button(btn_frame,
                                    text="查看代理",
                                    font=("Microsoft YaHei UI", 9),
                                    fg="white",
                                    bg=self.colors['accent'],
                                    bd=0,
                                    width=8,
                                    padx=5,
                                    pady=3,
                                    relief=tk.FLAT,
                                    cursor="hand2",
                                    command=lambda m=middleware_info: self.view_proxy_config(m))
            view_proxy_btn.pack(side=tk.LEFT, padx=5)
            
            # 创建其他控制按钮
            self.create_control_button(btn_frame, "启动",
                                    lambda mn=middleware_name: self.start_middleware(mn),
                                    self.colors['success'])
            
            if middleware_info.get('reload_cmd'):
                self.create_control_button(btn_frame, "重载",
                                        lambda mn=middleware_name: self.reload_middleware(mn),
                                        self.colors['accent'])
            
            self.create_control_button(btn_frame, "停止",
                                    lambda mn=middleware_name: self.stop_middleware(mn),
                                    self.colors['error'])
            
            delete_btn = self.create_control_button(btn_frame, "删除",
                                                  lambda mn=middleware_name: self.delete_middleware(mn),
                                                  "#9E9E9E")
            delete_btn.pack(padx=(15,5))
            
            # 添加鼠标悬停效果
            def on_enter(e, frame=inner_frame):
                frame.configure(bg=self.colors['bg'])
            def on_leave(e, frame=inner_frame):
                frame.configure(bg="white")
            
            inner_frame.bind("<Enter>", on_enter)
            inner_frame.bind("<Leave>", on_leave)

    def create_java_tab(self):
        """创建Java进程管理标签页"""
        # 创建标题
        title_frame = tk.Frame(self.java_tab, bg=self.colors['bg'])
        title_frame.pack(fill=tk.X, padx=20, pady=(20,10))
        
        title_label = tk.Label(title_frame, 
                             text="Java进程管理",
                             font=("Microsoft YaHei UI", 16, "bold"),
                             fg=self.colors['text'],
                             bg=self.colors['bg'])
        title_label.pack(side=tk.LEFT)
        
        # 添加新进程按钮
        add_btn = tk.Button(title_frame,
                          text="添加Java进程",
                          font=("Microsoft YaHei UI", 10),
                          fg="white",
                          bg=self.colors['accent'],
                          bd=0,
                          padx=15,
                          pady=5,
                          relief=tk.FLAT,
                          cursor="hand2",
                          command=self.add_new_java_process)
        add_btn.pack(side=tk.RIGHT)
        
        # 创建进程列表容器
        processes_frame = tk.Frame(self.java_tab, bg=self.colors['bg'])
        processes_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
        
        for service_name, service_info in self.java_services.items():
            # 创建进程卡片
            card = tk.Frame(processes_frame, bg="white", bd=0)
            card.pack(fill=tk.X, pady=10)
            
            # 添加圆角和阴影效果
            inner_frame = tk.Frame(card, bg="white", bd=1, relief=tk.SOLID)
            inner_frame.pack(fill=tk.BOTH, padx=2, pady=2)
            
            # 左侧信息区域
            info_frame = tk.Frame(inner_frame, bg="white")
            info_frame.pack(side=tk.LEFT, fill=tk.BOTH, padx=20, pady=15)
            
            # 进程名称
            tk.Label(info_frame,
                    text=service_name,
                    font=("Microsoft YaHei UI", 12, "bold"),
                    fg=self.colors['text'],
                    bg="white").pack(anchor=tk.W)
            
            # JAR包名称
            tk.Label(info_frame,
                    text=f"JAR: {service_info['jar_name']}",
                    font=("Microsoft YaHei UI", 9),
                    fg="gray",
                    bg="white").pack(anchor=tk.W, pady=(2,5))
            
            # 状态标签
            status_label = tk.Label(info_frame,
                                  text="检查中...",
                                  font=("Microsoft YaHei UI", 10),
                                  fg=self.colors['text'],
                                  bg="white")
            status_label.pack(anchor=tk.W)
            service_info["status_label"] = status_label
            
            # 右侧按钮区域
            btn_frame = tk.Frame(inner_frame, bg="white")
            btn_frame.pack(side=tk.RIGHT, fill=tk.Y, padx=20, pady=15)
            
            # 创建按钮
            self.create_control_button(btn_frame, "运行",
                                    lambda sn=service_name: self.run_java_service(sn),
                                    self.colors['success'])
            
            self.create_control_button(btn_frame, "停止",
                                    lambda sn=service_name: self.kill_java_process(sn),
                                    self.colors['error'])
            
            self.create_control_button(btn_frame, "配置",
                                    lambda sn=service_name: self.configure_script(sn),
                                    self.colors['warning'])
            
            delete_btn = self.create_control_button(btn_frame, "删除",
                                                  lambda sn=service_name: self.delete_java_process(sn),
                                                  "#9E9E9E")  # 使用灰色
            delete_btn.pack(padx=(15,5))  # 与其他按钮保持一定距离
            
            # 添加鼠标悬停效果
            def on_enter(e, frame=inner_frame):
                frame.configure(bg=self.colors['bg'])
            def on_leave(e, frame=inner_frame):
                frame.configure(bg="white")
            
            inner_frame.bind("<Enter>", on_enter)
            inner_frame.bind("<Leave>", on_leave)

    def show_service_tab(self):
        self.middleware_tab.pack_forget()
        self.java_tab.pack_forget()
        self.service_tab.pack(fill=tk.BOTH, expand=True)

    def show_middleware_tab(self):
        self.service_tab.pack_forget()
        self.java_tab.pack_forget()
        self.middleware_tab.pack(fill=tk.BOTH, expand=True)

    def show_java_tab(self):
        self.service_tab.pack_forget()
        self.middleware_tab.pack_forget()
        self.java_tab.pack(fill=tk.BOTH, expand=True)
    
    def configure_script(self, service_name):
        path = filedialog.askopenfilename(filetypes=[("Batch Files", "*.bat")])
        if path:
            self.java_services[service_name]["script"] = path
            self.save_java_services()  # 保存配置
        else:
            messagebox.showwarning("警告", "未选择脚本路径")
    
    def run_java_service(self, service_name):
        def _run():
            script_path = self.java_services[service_name]["script"]
            if not script_path:
                self.root.after(0, lambda: messagebox.showwarning("警告", "请先配置 {0} 的启动脚本路径".format(service_name)))
                return
                
            try:
                with self.operation_lock:
                    os.system(f'start "" "{script_path}"')
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror("错误", f"启动 {service_name} 失败: {e}"))
        
        threading.Thread(target=_run, daemon=True).start()

    def check_java_processes(self):
        """ 检测Java进程是否在运行，并更新状态 """
        # 先清空 PID 记录
        for service_name in self.java_services:
            self.java_services[service_name]["pid"] = None

        # 遍历进程，找到对应的 Java 进程
        for process in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                cmdline = " ".join(process.info['cmdline']) if process.info['cmdline'] else ""
                for service_name, service_info in self.java_services.items():
                    jar_name = service_info.get("jar_name", "")
                    if jar_name and jar_name in cmdline:
                        self.java_services[service_name]["pid"] = process.info['pid']
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue

        # 更新 UI
        for service_name, data in self.java_services.items():
            if data["pid"]:
                data["status_label"].config(text="运行中", fg="green")
            else:
                data["status_label"].config(text="未运行", fg="red")

    def kill_java_process(self, jar_name):
        """ 终止指定的 Java 进程 """
        def _kill():
            pid = self.java_services[jar_name]["pid"]
            if pid:
                try:
                    with self.operation_lock:
                        psutil.Process(pid).terminate()
                    self.root.after(0, lambda: messagebox.showinfo("成功", f"{jar_name} 已终止"))
                except Exception as e:
                    self.root.after(0, lambda: messagebox.showerror("错误", f"终止 {jar_name} 失败: {e}"))
            else:
                self.root.after(0, lambda: messagebox.showinfo("提示", f"{jar_name} 未运行"))
        
        threading.Thread(target=_kill, daemon=True).start()

    def start_service(self, service_name):
        def _start():
            try:
                with self.operation_lock:
                    win32serviceutil.StartService(self.services[service_name])
                self.root.after(0, lambda: messagebox.showinfo("成功", f"{service_name} 已启动"))
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror("错误", f"启动 {service_name} 失败: {e}"))
        
        threading.Thread(target=_start, daemon=True).start()

    def stop_service(self, service_name):
        def _stop():
            try:
                with self.operation_lock:
                    win32serviceutil.StopService(self.services[service_name])
                self.root.after(0, lambda: messagebox.showinfo("成功", f"{service_name} 已停止"))
            except Exception as error:
                self.root.after(0, lambda error=error: messagebox.showerror("错误", f"停止 {service_name} 失败: {error}"))
        
        threading.Thread(target=_stop, daemon=True).start()

    def restart_service(self, service_name):
        def _restart():
            try:
                with self.operation_lock:
                    win32serviceutil.RestartService(self.services[service_name])
                self.root.after(0, lambda: messagebox.showinfo("成功", f"{service_name} 已重启"))
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror("错误", f"重启 {service_name} 失败: {e}"))
        
        threading.Thread(target=_restart, daemon=True).start()
    
    def update_status(self):
        """ 更新所有服务和进程的状态 """
        try:
            # 检查服务状态
            service_status = {}
            for service_name in self.services:
                service_status[service_name] = self.is_service_running(service_name)
            
            # 检查Java进程状态
            java_status = self.check_java_processes_status()
            
            # 检查中间件状态
            middleware_status = self.check_middleware_processes_status()
            
            # 更新UI
            # 更新服务状态
            for service_name, is_running in service_status.items():
                if service_name in self.status_labels:
                    self.status_labels[service_name].config(
                        text="运行中" if is_running else "已停止",
                        fg="green" if is_running else "red"
                    )
            
            # 更新Java进程状态
            for service_name, data in java_status.items():
                if service_name in self.java_services:
                    self.java_services[service_name]["pid"] = data["pid"]
                    if "status_label" in self.java_services[service_name]:
                        self.java_services[service_name]["status_label"].config(
                            text="运行中" if data["pid"] else "未运行",
                            fg="green" if data["pid"] else "red"
                        )
            
            # 更新中间件状态
            for middleware_name, data in middleware_status.items():
                if middleware_name in self.middlewares:
                    self.middlewares[middleware_name]["pid"] = data["pid"]
                    if "status_label" in self.middlewares[middleware_name]:
                        self.middlewares[middleware_name]["status_label"].config(
                            text="运行中" if data["pid"] else "未运行",
                            fg="green" if data["pid"] else "red"
                        )
        except Exception as e:
            print(f"状态更新错误: {e}")
            
            # 每 3 秒更新一次状态
            self.root.after(3000, self.update_status)

    def is_service_running(self, service_name):
        service = self.services[service_name]
        try:
            status = win32serviceutil.QueryServiceStatus(service)
            return status[1] == win32service.SERVICE_RUNNING
        except Exception as e:
            print(f"检查服务状态失败: {e}")
            return False

    def load_java_services(self):
        try:
            if os.path.exists(self.config_file):
                try:
                    with open(self.config_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    # 添加运行时需要的字段
                    for service in data.values():
                        service["pid"] = None
                        service["status_label"] = None
                        # 确保script字段存在
                        if "script" not in service:
                            service["script"] = ""
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

    def save_java_services(self):
        try:
            # 创建一个不包含UI元素的副本
            services_to_save = {}
            for name, service in self.java_services.items():
                services_to_save[name] = {
                    "process": service["process"],
                    "jar_name": service["jar_name"],
                    "script": service.get("script", ""),  # 保存脚本路径
                }
            
            # 保存到文件
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(services_to_save, f, ensure_ascii=False, indent=4)
        except Exception as e:
            messagebox.showerror("错误", f"保存配置文件失败: {e}")

    def add_new_java_process(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("添加新进程")
        dialog.geometry("400x250")
        dialog.configure(bg="#f0f0f0")
        
        # 创建表单框架
        form_frame = tk.Frame(dialog, bg="#f0f0f0")
        form_frame.pack(pady=10, padx=20, fill=tk.X)
        
        # 进程名称输入
        tk.Label(form_frame, text="显示名称:", bg="#f0f0f0").pack(anchor=tk.W, pady=(5,0))
        name_entry = tk.Entry(form_frame, width=40)
        name_entry.pack(fill=tk.X, pady=(0,10))
        
        # JAR包选择
        tk.Label(form_frame, text="选择JAR包:", bg="#f0f0f0").pack(anchor=tk.W, pady=(5,0))
        
        jar_frame = tk.Frame(form_frame, bg="#f0f0f0")
        jar_frame.pack(fill=tk.X, pady=(0,10))
        
        jar_path_var = tk.StringVar()
        jar_path_label = tk.Label(jar_frame, textvariable=jar_path_var, bg="#ffffff", 
                                relief=tk.SUNKEN, anchor=tk.W, width=30)
        jar_path_label.pack(side=tk.LEFT, padx=(0,5))
        
        def select_jar():
            jar_file = filedialog.askopenfilename(
                filetypes=[("JAR Files", "*.jar"), ("All Files", "*.*")]
            )
            if jar_file:
                jar_path_var.set(os.path.basename(jar_file))
                jar_path_label.config(fg="black")
        
        select_button = tk.Button(jar_frame, text="浏览", command=select_jar,
                                bg="#FF9800", fg="white", width=8)
        select_button.pack(side=tk.LEFT)
        
        def submit():
            name = name_entry.get().strip()
            jar_name = jar_path_var.get().strip()
            
            if not name or not jar_name:
                messagebox.showwarning("警告", "请填写所有必填项")
                return
            if name in self.java_services:
                messagebox.showwarning("警告", "该进程名称已存在")
                return
                
            self.java_services[name] = {
                "process": name,
                "jar_name": jar_name,
                "script": "",
                "pid": None,
                "status_label": None
            }
            self.save_java_services()
            dialog.destroy()
            
            # 重新创建Java标签页
            for widget in self.java_tab.winfo_children():
                widget.destroy()
            self.create_java_tab()
            
        # 提交按钮
        button_frame = tk.Frame(dialog, bg="#f0f0f0")
        button_frame.pack(pady=20)
        
        submit_btn = tk.Button(button_frame, text="确定", command=submit, 
                             bg="#2196F3", fg="white", width=10)
        submit_btn.pack(side=tk.LEFT, padx=5)
        
        cancel_btn = tk.Button(button_frame, text="取消", command=dialog.destroy,
                             bg="#9E9E9E", fg="white", width=10)
        cancel_btn.pack(side=tk.LEFT, padx=5)

    def delete_java_process(self, service_name):
        if messagebox.askyesno("确认", f"确定要删除 {service_name} 吗？"):
            # 如果进程正在运行，先终止它
            if self.java_services[service_name]["pid"]:
                self.kill_java_process(service_name)
            
            # 删除进程配置
            del self.java_services[service_name]
            self.save_java_services()
            
            # 重新创建Java标签页
            for widget in self.java_tab.winfo_children():
                widget.destroy()
            self.create_java_tab()

    def load_middlewares(self):
        try:
            if os.path.exists(self.middleware_config_file):
                try:
                    with open(self.middleware_config_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    # 添加运行时需要的字段
                    for middleware in data.values():
                        middleware["pid"] = None
                        middleware["status_label"] = None
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
        except Exception as e:
            messagebox.showerror("错误", f"保存中间件配置失败: {e}")

    def add_new_middleware(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("添加新中间件")
        dialog.geometry("500x500")  # 增加窗口高度
        dialog.configure(bg="#f0f0f0")
        dialog.resizable(False, False)  # 禁止调整大小
        
        # 创建滚动区域
        canvas = tk.Canvas(dialog, bg="#f0f0f0", highlightthickness=0)
        scrollbar = tk.Scrollbar(dialog, orient="vertical", command=canvas.yview)
        scrollable_frame = tk.Frame(canvas, bg="#f0f0f0")
        
        # 配置滚动
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw", width=480)
        canvas.configure(yscrollcommand=scrollbar.set)
        
        # 创建表单框架
        form_frame = tk.Frame(scrollable_frame, bg="#f0f0f0")
        form_frame.pack(pady=10, padx=20, fill=tk.X)
        
        # 中间件名称输入
        tk.Label(form_frame, text="显示名称:", bg="#f0f0f0", font=("Arial", 10, "bold")).pack(anchor=tk.W, pady=(5,0))
        name_entry = tk.Entry(form_frame, width=40)
        name_entry.pack(fill=tk.X, pady=(5,10))
        
        # 进程名称输入
        tk.Label(form_frame, text="进程名称:", bg="#f0f0f0", font=("Arial", 10, "bold")).pack(anchor=tk.W, pady=(5,0))
        tk.Label(form_frame, text="(用于进程检测，例如: nginx.exe)", bg="#f0f0f0", fg="gray").pack(anchor=tk.W)
        process_entry = tk.Entry(form_frame, width=40)
        process_entry.pack(fill=tk.X, pady=(5,10))
        
        # 启动命令输入
        tk.Label(form_frame, text="启动命令:", bg="#f0f0f0", font=("Arial", 10, "bold")).pack(anchor=tk.W, pady=(5,0))
        tk.Label(form_frame, text="(例如: start nginx.exe)", bg="#f0f0f0", fg="gray").pack(anchor=tk.W)
        start_cmd_entry = tk.Entry(form_frame, width=40)
        start_cmd_entry.pack(fill=tk.X, pady=(5,10))
        
        # 重载命令输入
        tk.Label(form_frame, text="重载命令:", bg="#f0f0f0", font=("Arial", 10, "bold")).pack(anchor=tk.W, pady=(5,0))
        tk.Label(form_frame, text="(例如: nginx.exe -s reload)", bg="#f0f0f0", fg="gray").pack(anchor=tk.W)
        reload_cmd_entry = tk.Entry(form_frame, width=40)
        reload_cmd_entry.pack(fill=tk.X, pady=(5,10))
        
        # 工作目录选择
        tk.Label(form_frame, text="工作目录:", bg="#f0f0f0", font=("Arial", 10, "bold")).pack(anchor=tk.W, pady=(5,0))
        
        dir_frame = tk.Frame(form_frame, bg="#f0f0f0")
        dir_frame.pack(fill=tk.X, pady=(5,10))
        
        dir_path_var = tk.StringVar()
        dir_path_label = tk.Label(dir_frame, textvariable=dir_path_var, bg="#ffffff",
                                relief=tk.SUNKEN, anchor=tk.W)
        dir_path_label.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0,5))
        
        def select_dir():
            dir_path = filedialog.askdirectory()
            if dir_path:
                dir_path_var.set(dir_path)
                dir_path_label.config(fg="black")
        
        select_button = tk.Button(dir_frame, text="浏览", command=select_dir,
                                bg="#FF9800", fg="white", width=8)
        select_button.pack(side=tk.LEFT)
        
        def submit():
            name = name_entry.get().strip()
            process_name = process_entry.get().strip()
            start_cmd = start_cmd_entry.get().strip()
            reload_cmd = reload_cmd_entry.get().strip()
            work_dir = dir_path_var.get().strip()
            
            # 验证和清理进程名称
            process_name = process_name.replace(",", ".").strip()  # 将逗号替换为点
            if not process_name.endswith(".exe"):
                process_name = f"{process_name}.exe"
            
            if not all([name, process_name, start_cmd]):
                messagebox.showwarning("警告", "请填写必填项（显示名称、进程名称、启动命令）")
                return
            if name in self.middlewares:
                messagebox.showwarning("警告", "该中间件名称已存在")
                return
                
            self.middlewares[name] = {
                "process_name": process_name,
                "start_cmd": start_cmd,
                "reload_cmd": reload_cmd,
                "work_dir": work_dir,
                "pid": None,
                "status_label": None,
                "port": self.get_nginx_port(os.path.join(work_dir, "nginx.conf"))
            }
            self.save_middlewares()
            dialog.destroy()
            
            # 重新创建中间件标签页
            for widget in self.middleware_tab.winfo_children():
                widget.destroy()
            self.create_middleware_tab()
        
        # 分隔线
        separator = tk.Frame(scrollable_frame, height=2, bg="#e0e0e0")
        separator.pack(fill=tk.X, padx=20, pady=10)
        
        # 提交按钮
        button_frame = tk.Frame(scrollable_frame, bg="#f0f0f0")
        button_frame.pack(pady=10, padx=20, fill=tk.X)
        
        submit_btn = tk.Button(button_frame, text="确定", command=submit,
                             bg="#2196F3", fg="white", width=10)
        submit_btn.pack(side=tk.LEFT, padx=5)
        
        cancel_btn = tk.Button(button_frame, text="取消", command=dialog.destroy,
                             bg="#9E9E9E", fg="white", width=10)
        cancel_btn.pack(side=tk.LEFT, padx=5)
        
        # 布局滚动区域
        canvas.pack(side="left", fill="both", expand=True, padx=(10,0))
        scrollbar.pack(side="right", fill=tk.Y, padx=(0,10))
        
        # 设置对话框位置为屏幕中心
        dialog.update_idletasks()
        width = dialog.winfo_width()
        height = dialog.winfo_height()
        x = (dialog.winfo_screenwidth() // 2) - (width // 2)
        y = (dialog.winfo_screenheight() // 2) - (height // 2)
        dialog.geometry(f"{width}x{height}+{x}+{y}")
        
        # 设置模态
        dialog.transient(self.root)
        dialog.grab_set()

    def start_middleware(self, middleware_name):
        def _start():
            middleware = self.middlewares[middleware_name]
            work_dir = middleware.get("work_dir", "")
            
            if work_dir:
                current_dir = os.getcwd()
                os.chdir(work_dir)
                
            try:
                with self.operation_lock:
                    os.system(middleware["start_cmd"])
                if work_dir:
                    os.chdir(current_dir)
            except Exception as e:
                if work_dir:
                    os.chdir(current_dir)
                self.root.after(0, lambda: messagebox.showerror("错误", f"启动 {middleware_name} 失败: {e}"))
        
        threading.Thread(target=_start, daemon=True).start()

    def reload_middleware(self, middleware_name):
        middleware = self.middlewares[middleware_name]
        if not middleware["reload_cmd"]:
            messagebox.showwarning("警告", f"{middleware_name} 未配置重载命令")
            return
            
        work_dir = middleware.get("work_dir", "")
        if work_dir:
            current_dir = os.getcwd()
            os.chdir(work_dir)
            
        try:
            with self.operation_lock:
                # 执行重载命令
                result = os.system(middleware["reload_cmd"])
                if result == 0:
                    messagebox.showinfo("成功", f"{middleware_name} 重载成功")
                else:
                    messagebox.showerror("错误", f"{middleware_name} 重载失败，返回代码：{result}")
            if work_dir:
                os.chdir(current_dir)
        except Exception as e:
            if work_dir:
                os.chdir(current_dir)
            messagebox.showerror("错误", f"重载 {middleware_name} 失败: {e}")

    def stop_middleware(self, middleware_name):
        def _stop():
            middleware = self.middlewares[middleware_name]
            process_name = middleware['process_name'].lower()
            work_dir = middleware.get("work_dir", "").lower()
            stopped = False

            try:
                with self.operation_lock:
                    # 获取所有进程
                    for proc in psutil.process_iter(['pid', 'name', 'exe', 'cwd']):
                        try:
                            # 检查进程名是否匹配
                            if (proc.info['name'].lower() == process_name or
                                (proc.info['exe'] and os.path.basename(proc.info['exe']).lower() == process_name)):
                                
                                # 如果配置了工作目录，进行检查
                                if work_dir:
                                    try:
                                        proc_cwd = proc.cwd().lower()
                                        if not (work_dir in proc_cwd or 
                                              proc_cwd in work_dir or 
                                              os.path.normpath(work_dir) == os.path.normpath(proc_cwd)):
                                            continue
                                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                                        continue

                                # 终止进程
                                proc.terminate()
                                stopped = True
                                
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            continue

                    if stopped:
                        self.root.after(0, lambda: messagebox.showinfo("成功", f"{middleware_name} 的所有相关进程已停止"))
                    else:
                        self.root.after(0, lambda: messagebox.showinfo("提示", f"{middleware_name} 未运行"))
            except Exception as error:
                self.root.after(0, lambda error=error: messagebox.showerror("错误", f"停止 {middleware_name} 失败: {error}"))
        
        threading.Thread(target=_stop, daemon=True).start()

    def delete_middleware(self, middleware_name):
        if messagebox.askyesno("确认", f"确定要删除 {middleware_name} 吗？"):
            # 如果进程正在运行，先终止它
            if self.middlewares[middleware_name]["pid"]:
                self.stop_middleware(middleware_name)
            
            # 删除配置
            del self.middlewares[middleware_name]
            self.save_middlewares()
            
            # 重新创建中间件标签页
            for widget in self.middleware_tab.winfo_children():
                widget.destroy()
            self.create_middleware_tab()

    def background_status_check(self):
        """后台状态检查线程"""
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
                
                # 将状态放入队列
                self.status_queue.put({
                    'services': service_status,
                    'java': java_status,
                    'middleware': middleware_status
                })
                
                # 通知主线程更新UI
                self.root.after(0, self.update_ui_status)
                
                # 休眠时间改为和检查间隔一致
                time.sleep(self.CHECK_INTERVAL)
            except Exception as e:
                print(f"状态检查错误: {e}")
                time.sleep(1)

    def update_ui_status(self):
        """在主线程中更新UI状态"""
        try:
            # 非阻塞方式获取状态
            status = self.status_queue.get_nowait()
            
            # 更新服务状态
            for service_name, is_running in status['services'].items():
                if service_name in self.status_labels:
                    self.status_labels[service_name].config(
                        text="运行中" if is_running else "已停止",
                        fg="green" if is_running else "red"
                    )
            
            # 更新Java进程状态
            for service_name, data in status['java'].items():
                if service_name in self.java_services:
                    self.java_services[service_name]["pid"] = data["pid"]
                    if "status_label" in self.java_services[service_name]:
                        self.java_services[service_name]["status_label"].config(
                            text="运行中" if data["pid"] else "未运行",
                            fg="green" if data["pid"] else "red"
                        )
            
            # 更新中间件状态
            for middleware_name, data in status['middleware'].items():
                if middleware_name in self.middlewares:
                    self.middlewares[middleware_name]["pid"] = data["pid"]
                    if "status_label" in self.middlewares[middleware_name]:
                        self.middlewares[middleware_name]["status_label"].config(
                            text="运行中" if data["pid"] else "未运行",
                            fg="green" if data["pid"] else "red"
                        )
        except queue.Empty:
            pass
        except Exception as e:
            print(f"UI更新错误: {e}")

    def check_java_processes_status(self):
        """检查Java进程状态（非UI操作）"""
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
        """检查中间件状态（非UI操作）"""
        current_time = time.time()
        
        # 如果距离上次检查时间不足CHECK_INTERVAL秒，直接返回缓存的结果
        if current_time - self.last_check_time < self.CHECK_INTERVAL:
            return self.process_cache
            
        status = {}
        for middleware_name in self.middlewares:
            status[middleware_name] = {"pid": None}
            
        # 首先尝试使用tasklist命令获取进程信息（效率更高）
        try:
            import subprocess
            # 一次性获取所有进程信息
            tasklist_output = subprocess.check_output('tasklist /FO CSV /NH', shell=True).decode('gbk')
            
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
            pass  # 如果tasklist失败，静默处理，继续使用psutil
            
        # 如果tasklist方法没有找到某些进程，使用psutil作为备选方案
        try:
            # 一次性获取所有进程信息
            processes = {p.info['pid']: p for p in psutil.process_iter(['pid', 'name', 'exe'])}
            
            for middleware_name, middleware_info in self.middlewares.items():
                if status[middleware_name]["pid"]:  # 如果已经找到了进程，跳过
                    continue
                    
                process_name = middleware_info['process_name'].lower()
                work_dir = middleware_info.get("work_dir", "").lower()
                
                # 在进程列表中查找匹配的进程
                for pid, proc in processes.items():
                    try:
                        if (proc.info['name'].lower() == process_name or
                            (proc.info['exe'] and os.path.basename(proc.info['exe']).lower() == process_name)):
                            
                            # 如果配置了工作目录，进行检查
                            if work_dir:
                                try:
                                    proc_cwd = proc.cwd().lower()
                                    if not (work_dir in proc_cwd or 
                                          proc_cwd in work_dir or 
                                          os.path.normpath(work_dir) == os.path.normpath(proc_cwd)):
                                        continue
                                except (psutil.NoSuchProcess, psutil.AccessDenied):
                                    continue
                        
                            status[middleware_name]["pid"] = pid
                            break
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
                        
        except Exception:
            pass
            
        # 更新缓存和最后检查时间
        self.process_cache = status
        self.last_check_time = current_time
                
        return status

    def adjust_color(self, color, amount):
        """调整颜色深浅
        color: 十六进制颜色值
        amount: 调整量（正数变亮，负数变暗）
        """
        def clamp(x): 
            return max(0, min(x, 255))
            
        # 去掉#号，转换为RGB
        c = color.lstrip('#')
        r, g, b = tuple(int(c[i:i+2], 16) for i in (0, 2, 4))
        
        # 调整每个颜色通道
        r = clamp(r + amount)
        g = clamp(g + amount)
        b = clamp(b + amount)
        
        # 转回十六进制格式
        return f"#{r:02x}{g:02x}{b:02x}"

    def get_nginx_port(self, nginx_conf_path):
        """读取nginx配置文件中的端口号"""
        try:
            with open(nginx_conf_path, 'r', encoding='utf-8') as f:
                content = f.read()
                # 使用简单的文本匹配查找端口号
                match = re.search(r'listen\s+(\d+)', content)
                if match:
                    return match.group(1)
        except Exception as e:
            messagebox.showerror("错误", f"读取nginx配置文件失败: {e}")
        return None

    def update_nginx_port(self, nginx_conf_path, new_port):
        """更新nginx配置文件中的端口号"""
        try:
            with open(nginx_conf_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # 使用正则表达式替换端口号
            new_content = re.sub(r'(listen\s+)\d+', rf'\g<1>{new_port}', content)
            
            with open(nginx_conf_path, 'w', encoding='utf-8') as f:
                f.write(new_content)
            
            return True
        except Exception as e:
            messagebox.showerror("错误", f"更新nginx配置文件失败: {e}")
            return False

    def add_proxy_config(self, middleware_info):
        """添加Nginx代理配置"""
        work_dir = middleware_info.get("work_dir", "")
        if not work_dir:
            messagebox.showwarning("警告", "请先设置nginx的工作目录")
            return
        
        nginx_conf = os.path.join(work_dir, "conf", "nginx.conf")
        if not os.path.exists(nginx_conf):
            messagebox.showwarning("警告", "未找到nginx配置文件")
            return
        
        # 定义需要过滤的路径列表
        filter_paths = [
            r"location\s+/api/",
            r"location\s+/admin/api/files/upload/",
            r"location\s+/papi/",
            r"location\s+/www",
            r"location\s+/",
            r"location\s+/authcenter/",
            r"location\s+/usercenter/",
            r"location\s+/permissions/",
            r"location\s+/wish3dearth/",
            r"location\s+/datamanage/",
            r"location\s+~\s+\^/wish3dearth/static/v1\.0\.0/cad/api/v1/map/\(.*\)\$"
        ]
        
        # 创建对话框
        dialog = tk.Toplevel(self.root)
        dialog.title("添加反向代理配置")
        dialog.geometry("400x200")
        dialog.configure(bg="#f0f0f0")
        
        # 使对话框成为模态
        dialog.transient(self.root)
        dialog.grab_set()
        
        # 创建表单框架
        form_frame = tk.Frame(dialog, bg="#f0f0f0")
        form_frame.pack(pady=20, padx=20, fill=tk.X)
        
        # 代理后缀输入
        tk.Label(form_frame, text="代理后缀:", bg="#f0f0f0").pack(anchor=tk.W)
        suffix_var = tk.StringVar()
        suffix_entry = tk.Entry(form_frame, textvariable=suffix_var, width=40)
        suffix_entry.pack(fill=tk.X, pady=(5,15))
        
        # 目标地址输入
        tk.Label(form_frame, text="目标地址:", bg="#f0f0f0").pack(anchor=tk.W)
        target_var = tk.StringVar()
        target_entry = tk.Entry(form_frame, textvariable=target_var, width=40)
        target_entry.pack(fill=tk.X, pady=(5,15))
        
        def submit():
            suffix = suffix_var.get().strip()
            target = target_var.get().strip()
            
            if not suffix or not target:
                messagebox.showwarning("警告", "请填写所有字段")
                return
            
            # 确保后缀以/开头
            if not suffix.startswith('/'):
                suffix = '/' + suffix
            
            # 读取nginx配置文件
            try:
                with open(nginx_conf, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # 查找server_name行
                server_block = re.search(r'server\s*{[^}]*server_name[^;]*;', content, re.DOTALL)
                if not server_block:
                    messagebox.showerror("错误", "无法在配置文件中找到server配置块")
                    return
                
                # 构建新的location配置
                location_config = f"\n    location {suffix} {{\n        proxy_pass {target};\n    }}"
                
                # 在server_name后插入location配置
                insert_pos = server_block.end()
                new_content = content[:insert_pos] + location_config + content[insert_pos:]
                
                # 写入配置文件
                with open(nginx_conf, 'w', encoding='utf-8') as f:
                    f.write(new_content)
                
                # 重载nginx
                self.reload_middleware(next(name for name, info in self.middlewares.items() 
                                         if info == middleware_info))
                
                messagebox.showinfo("成功", "代理配置已添加并重载nginx")
                dialog.destroy()
                
            except Exception as e:
                messagebox.showerror("错误", f"更新nginx配置文件失败: {e}")
        
        # 按钮区域
        button_frame = tk.Frame(dialog, bg="#f0f0f0")
        button_frame.pack(pady=10)
        
        submit_btn = tk.Button(button_frame, text="确定", command=submit,
                             bg="#2196F3", fg="white", width=10)
        submit_btn.pack(side=tk.LEFT, padx=5)
        
        cancel_btn = tk.Button(button_frame, text="取消", command=dialog.destroy,
                             bg="#9E9E9E", fg="white", width=10)
        cancel_btn.pack(side=tk.LEFT, padx=5)
        
        # 设置对话框位置为屏幕中心
        dialog.update_idletasks()
        width = dialog.winfo_width()
        height = dialog.winfo_height()
        x = (dialog.winfo_screenwidth() // 2) - (width // 2)
        y = (dialog.winfo_screenheight() // 2) - (height // 2)
        dialog.geometry(f"{width}x{height}+{x}+{y}")

    def view_proxy_config(self, middleware_info):
        """查看Nginx代理配置"""
        work_dir = middleware_info.get("work_dir", "")
        if not work_dir:
            messagebox.showwarning("警告", "请先设置nginx的工作目录")
            return
        
        nginx_conf = os.path.join(work_dir, "conf", "nginx.conf")
        if not os.path.exists(nginx_conf):
            messagebox.showwarning("警告", "未找到nginx配置文件")
            return
        
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
        
        # 创建对话框
        dialog = tk.Toplevel(self.root)
        dialog.title("查看代理配置")
        dialog.geometry("600x400")
        dialog.configure(bg="#f0f0f0")
        
        # 使对话框成为模态
        dialog.transient(self.root)
        dialog.grab_set()
        
        # 创建表格框架
        frame = tk.Frame(dialog, bg="#f0f0f0")
        frame.pack(pady=20, padx=20, fill=tk.BOTH, expand=True)
        
        # 创建表格
        columns = ("代理路径", "目标地址")
        tree = ttk.Treeview(frame, columns=columns, show="headings")
        
        # 设置列标题
        for col in columns:
            tree.heading(col, text=col)
            tree.column(col, width=250)
        
        # 添加滚动条
        scrollbar = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        
        # 读取nginx配置文件并解析代理配置
        try:
            with open(nginx_conf, 'r', encoding='utf-8') as f:
                content = f.read()
                
            # 使用正则表达式查找所有location配置
            locations = re.finditer(r'location\s+([^{]+)\s*{\s*proxy_pass\s+([^;]+);', content)
            
            # 添加到表格中，但过滤掉指定的路径
            for match in locations:
                location_block = f"location {match.group(1)}"
                
                # 检查是否需要过滤
                should_filter = False
                for filter_path in filter_paths:
                    if re.match(filter_path, location_block.strip()):
                        should_filter = True
                        break
                
                # 如果不需要过滤，则添加到表格中
                if not should_filter:
                    path = match.group(1).strip()
                    target = match.group(2).strip()
                    tree.insert("", tk.END, values=(path, target))
                
        except Exception as e:
            messagebox.showerror("错误", f"读取nginx配置文件失败: {e}")
            dialog.destroy()
            return
        
        # 布局表格和滚动条
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # 添加关闭按钮
        btn_frame = tk.Frame(dialog, bg="#f0f0f0")
        btn_frame.pack(pady=10)
        
        close_btn = tk.Button(btn_frame, text="关闭", command=dialog.destroy,
                             bg="#9E9E9E", fg="white", width=10)
        close_btn.pack(padx=5)
        
        # 设置对话框位置为屏幕中心
        dialog.update_idletasks()
        width = dialog.winfo_width()
        height = dialog.winfo_height()
        x = (dialog.winfo_screenwidth() // 2) - (width // 2)
        y = (dialog.winfo_screenheight() // 2) - (height // 2)
        dialog.geometry(f"{width}x{height}+{x}+{y}")

    def __del__(self):
        """清理资源"""
        self.is_running = False
        if hasattr(self, 'status_thread'):
            self.status_thread.join(timeout=1)
        if hasattr(self, 'tray_icon'):
            self.tray_icon.stop()

def main():
    # 创建主窗口
    root = tk.Tk()
    app = ServiceManagerApp(root)
    
    # 设置系统托盘
    app.setup_tray()
    
    # 运行主循环
    root.mainloop()

if __name__ == "__main__":
    if sys.platform.startswith('win'):
        # 如果是Windows系统，隐藏控制台窗口
        import ctypes
        ctypes.windll.user32.ShowWindow(
            ctypes.windll.kernel32.GetConsoleWindow(), 0)
    main()

#print("当前中间件配置：")
#for name, info in app.middlewares.items():
#    print(f"名称: {name}")
#    print(f"进程名: {info['process_name']}")
#    print(f"工作目录: {info.get('work_dir', '未设置')}")
#    print("---")