import sys
import os
import datetime
import re
from pathlib import Path
from PyQt5.QtWidgets import QApplication, QMainWindow, QFileDialog, QMessageBox
from PyQt5.QtCore import QThread, pyqtSignal, Qt
from MainUi_ui import Ui_MainWindow
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from PyQt5 import QtGui
import shutil

def get_script_dir() -> Path:
    """获取脚本（或打包后 exe）所在目录"""
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent
    return Path(__file__).parent.resolve()

def move_file(src: str, dst: Path, copy_only: bool = False) -> None:
    """
    移动或复制单个文件，处理重名情况
    """
    src_path = Path(src)
    
    # 如果目标文件已存在，则进行重命名
    counter = 1
    target = dst
    while target.exists():
        stem = target.stem
        suffix = target.suffix
        # 如果已存在，则在文件名后加上计数器
        target = target.with_name(f"{stem}({counter}){suffix}")
        counter += 1

    try:
        if copy_only:
            # 复制文件（保留原文件）
            shutil.copy2(str(src_path), str(target))
        else:
            # 移动文件（剪切）
            shutil.move(str(src_path), str(target))
    except Exception as e:
        raise Exception(f'{"复制" if copy_only else "移动"}失败：{src_path} -> {target}  {e}')

class FileProcessingThread(QThread):
    """文件处理线程，避免UI卡顿"""
    progress_updated = pyqtSignal(int)
    log_updated = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, wechat_path, output_path, keep_original, use_date_category):
        super().__init__()
        self.wechat_path = wechat_path
        self.output_path = output_path
        self.keep_original = keep_original
        self.use_date_category = use_date_category
        self.is_running = True

    def run(self):
        try:
            # 验证输入路径
            wechat_dir = Path(self.wechat_path)
            if not wechat_dir.is_dir():
                self.log_updated.emit("[错误] 微信文件夹路径无效")
                self.finished.emit()
                return

            # 扫描月份文件夹 (格式: YYYY-MM)
            month_dirs = [p for p in wechat_dir.iterdir() 
                         if p.is_dir() and re.match(r'\d{4}-\d{2}', p.name)]
            self.log_updated.emit(f"发现 {len(month_dirs)} 个月份文件夹: {[d.name for d in month_dirs]}")

            # 按文件类型分类
            files_by_type = defaultdict(list)
            for month_folder in month_dirs:
                if not self.is_running:  # 检查是否需要终止
                    break
                self.log_updated.emit(f"扫描文件夹: {month_folder.name}")
                for file_path in month_folder.rglob('*'):
                    if file_path.is_file():
                        # 处理文件后缀
                        suffix = file_path.suffix.lower()
                        if suffix:  # 有后缀名
                            suffix = suffix[1:]  # 去掉点号
                        else:  # 无后缀名
                            suffix = 'no_ext'
                        files_by_type[suffix].append(str(file_path.resolve()))

            if not self.is_running:
                self.log_updated.emit("操作已取消")
                self.finished.emit()
                return

            # 计算总文件数
            total_files = sum(len(v) for v in files_by_type.values())
            self.log_updated.emit(f"总计 {len(files_by_type)} 种文件类型，{total_files} 个文件")

            # 准备输出目录
            out_root = Path(self.output_path).resolve() if self.output_path else get_script_dir()
            self.log_updated.emit(f"输出根目录：{out_root}")
            
            # 日志显示是否按日期分类
            if self.use_date_category:
                self.log_updated.emit("将按文件修改日期进行二次分类（格式：YYYY-MM-DD）")
            else:
                self.log_updated.emit("不按日期进行二次分类")

            # 创建类型目录（一级分类：按后缀）
            type_dir_map = {}
            for suf in files_by_type.keys():
                target = out_root / 'Files' / suf
                target.mkdir(parents=True, exist_ok=True)
                type_dir_map[suf] = target

            # 准备任务列表
            tasks = []
            for suf, file_list in files_by_type.items():
                type_dir = type_dir_map[suf]  # 一级目录：Files/<后缀>
                for src in file_list:
                    src_path = Path(src)
                    # 根据开关决定是否添加日期子目录（二级分类）
                    if self.use_date_category:
                        try:
                            # 获取文件修改时间
                            mtime = src_path.stat().st_mtime
                            date_str = datetime.datetime.fromtimestamp(mtime).strftime('%Y-%m-%d')
                            date_dir = type_dir / date_str  # 二级目录：Files/<后缀>/YYYY-MM-DD
                            date_dir.mkdir(parents=True, exist_ok=True)
                            dst = date_dir / src_path.name
                        except Exception as e:
                            self.log_updated.emit(f"[警告] 无法获取文件 {src} 的日期信息，将直接保存到类型目录：{e}")
                            dst = type_dir / src_path.name
                    else:
                        # 不按日期分类，直接保存到类型目录
                        dst = type_dir / src_path.name
                    tasks.append((src, dst, self.keep_original))

            if not tasks:
                self.log_updated.emit("未找到可处理的文件")
                self.finished.emit()
                return

            # 执行多线程处理
            self.log_updated.emit(f"开始处理 {len(tasks)} 个文件...")
            completed = 0
            WORKERS = min(32, len(tasks))  # 避免创建过多线程
            with ThreadPoolExecutor(max_workers=WORKERS) as pool:
                futures = [pool.submit(move_file, src, dst, copy_only) for src, dst, copy_only in tasks]
                for fut in as_completed(futures):
                    if not self.is_running:  # 检查取消状态
                        # 尝试取消未完成的任务
                        for f in futures:
                            f.cancel()
                        break
                    
                    # 处理可能出现的异常
                    try:
                        fut.result()
                    except Exception as e:
                        self.log_updated.emit(f"[错误] {str(e)}")
                    
                    completed += 1
                    # 更新进度条
                    progress = int((completed / len(tasks)) * 100)
                    self.progress_updated.emit(progress)
                    # 每10个任务更新一次日志
                    if completed % 10 == 0 or completed == len(tasks):
                        self.log_updated.emit(f"已完成 {completed}/{len(tasks)}")

            if self.is_running:
                self.log_updated.emit("全部处理完成！")
            else:
                self.log_updated.emit("处理已取消")

        except Exception as e:
            self.log_updated.emit(f"[错误] {str(e)}")
        finally:
            self.finished.emit()

    def stop(self):
        self.is_running = False

class MainWindow(QMainWindow, Ui_MainWindow):
    def __init__(self):
        super().__init__()
        self.setupUi(self)
        self.init_ui()

    def init_ui(self):
        # 设置窗口标题
        self.setWindowTitle("微信文件分拣器")
        # 绑定按钮事件
        self.ChooseWeChatFile_2.clicked.connect(self.choose_wechat_dir)
        self.ChooseOutPutFile_2.clicked.connect(self.choose_output_dir)
        self.Start_2.clicked.connect(self.start_processing)
        self.Cancel_2.clicked.connect(self.cancel_processing)
        # 初始化线程
        self.processing_thread = None

        # 设置SwitchButton默认开启
        self.SwitchButton.setChecked(True)
        # 设置日期分类开关默认状态
        self.DateSwitchButton.setChecked(False)
        
        # 初始化日志
        self.append_log("欢迎使用微信文件分拣器")
        self.append_log("请选择微信文件夹路径（包含月份文件夹的目录）")

    def choose_wechat_dir(self):
        """选择微信文件夹"""
        dir_path = QFileDialog.getExistingDirectory(
            self, "选择微信文件夹", str(get_script_dir())
        )
        if dir_path:
            self.wechatlineEdit_2.setText(dir_path)
            # 检查是否是有效的微信文件夹（包含月份文件夹）
            path = Path(dir_path)
            if path.is_dir():
                month_dirs = [p for p in path.iterdir() 
                             if p.is_dir() and re.match(r'\d{4}-\d{2}', p.name)]
                if month_dirs:
                    self.append_log(f"检测到 {len(month_dirs)} 个月份文件夹")
                else:
                    self.append_log("警告：未检测到月份文件夹（格式：YYYY-MM）")

    def choose_output_dir(self):
        """选择输出文件夹"""
        dir_path = QFileDialog.getExistingDirectory(
            self, "选择输出文件夹", str(get_script_dir())
        )
        if dir_path:
            self.outputlineEdit_2.setText(dir_path)

    def start_processing(self):
        """开始处理文件"""
        # 读取开关状态
        keep_original = self.SwitchButton.isChecked()
        use_date_category = self.DateSwitchButton.isChecked()

        wechat_path = self.wechatlineEdit_2.text().strip()
        output_path = self.outputlineEdit_2.text().strip()

        # 验证路径
        if not wechat_path:
            QMessageBox.warning(self, "警告", "请选择微信文件夹路径")
            return
            
        # 检查路径是否包含月份文件夹
        path = Path(wechat_path)
        if path.is_dir():
            month_dirs = [p for p in path.iterdir() 
                         if p.is_dir() and re.match(r'\d{4}-\d{2}', p.name)]
            if not month_dirs:
                reply = QMessageBox.question(self, "确认", 
                                           "未检测到月份文件夹（格式：YYYY-MM），是否继续？",
                                           QMessageBox.Yes | QMessageBox.No)
                if reply == QMessageBox.No:
                    return

        # 禁用按钮防止重复点击
        self.Start_2.setEnabled(False)
        self.Cancel_2.setEnabled(True)
        self.progressBar.setValue(0)
        self.LogTextBrowser.clear()

        # 创建并启动处理线程
        self.processing_thread = FileProcessingThread(
            wechat_path, output_path, keep_original, use_date_category
        )
        self.processing_thread.progress_updated.connect(self.progressBar.setValue)
        self.processing_thread.log_updated.connect(self.append_log)
        self.processing_thread.finished.connect(self.on_process_finished)
        self.processing_thread.start()

    def cancel_processing(self):
        """取消处理"""
        if self.processing_thread and self.processing_thread.isRunning():
            self.append_log("正在取消处理...")
            self.processing_thread.stop()
            self.Cancel_2.setEnabled(False)

    def append_log(self, text):
        """追加日志到文本浏览器"""
        self.LogTextBrowser.append(text)
        # 自动滚动到底部
        self.LogTextBrowser.moveCursor(QtGui.QTextCursor.End)

    def on_process_finished(self):
        """处理完成回调"""
        self.Start_2.setEnabled(True)
        self.Cancel_2.setEnabled(False)
        self.processing_thread = None

    def closeEvent(self, event):
        """窗口关闭时确保线程终止"""
        if self.processing_thread and self.processing_thread.isRunning():
            self.processing_thread.stop()
            self.processing_thread.wait(5000)  # 等待5秒
        event.accept()

if __name__ == "__main__":
    # 确保中文显示正常
    font = QtGui.QFont("微软雅黑")
    app = QApplication(sys.argv)
    app.setFont(font)
    
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())