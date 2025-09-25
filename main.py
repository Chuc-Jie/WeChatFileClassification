import sys
import os
from pathlib import Path
from PyQt5.QtWidgets import QApplication, QMainWindow, QFileDialog, QMessageBox
from PyQt5.QtCore import QThread, pyqtSignal, Qt
from MainUi_ui import Ui_MainWindow
from Multithreading import get_script_dir, move_one, defaultdict, ThreadPoolExecutor, as_completed
from PyQt5 import QtGui

class FileProcessingThread(QThread):
    """文件处理线程，避免UI卡顿"""
    progress_updated = pyqtSignal(int)
    log_updated = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, wechat_path, output_path, keep_original):
        super().__init__()
        self.wechat_path = wechat_path
        self.output_path = output_path
        self.keep_original = keep_original  # 保存开关状态
        self.is_running = True

    def run(self):
        try:
            # 验证输入路径
            file_dir = Path(self.wechat_path).parent
            if not file_dir.is_dir():
                self.log_updated.emit("[错误] 微信文件夹路径无效")
                self.finished.emit()
                return

            # 扫描子目录
            sub_dirs = [p for p in file_dir.iterdir() if p.is_dir() and p.is_dir()]
            self.log_updated.emit(f"发现 {len(sub_dirs)} 个月份文件夹")

            # 按文件类型分类
            files_by_type = defaultdict(list)
            for folder in sub_dirs:
                if not self.is_running:  # 检查是否需要终止
                    break
                for file in folder.rglob('*'):
                    if file.is_file():
                        suffix = file.suffix.lstrip('.').lower() or 'no_ext'
                        files_by_type[suffix].append(str(file.resolve()))

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

            # 创建类型目录
            type_dir_map = {}
            for suf in files_by_type.keys():
                target = out_root / 'Files' / suf
                target.mkdir(parents=True, exist_ok=True)
                type_dir_map[suf] = target

            # 准备任务列表
            tasks = []
            for suf, file_list in files_by_type.items():
                root = type_dir_map[suf]
                tasks.extend([(src, root / Path(src).name, self.keep_original) for src in file_list])

            # 执行多线程移动
            self.log_updated.emit(f"开始处理 {len(tasks)} 个文件...")
            completed = 0
            WORKERS = 32
            with ThreadPoolExecutor(max_workers=WORKERS) as pool:
                futures = [pool.submit(move_one, src, dst, copy_only) for src, dst, copy_only in tasks]
                for fut in as_completed(futures):
                    if not self.is_running:  # 检查取消状态
                        pool.shutdown(wait=False, cancel_futures=True)
                        break
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

        # 设置SwitchButton默认开启（关键代码）
        self.SwitchButton.setChecked(True)

    def choose_wechat_dir(self):
        """选择微信文件夹"""
        dir_path = QFileDialog.getExistingDirectory(
            self, "选择微信文件夹", str(get_script_dir())
        )
        if dir_path:
            self.wechatlineEdit_2.setText(dir_path)

    def choose_output_dir(self):
        """选择输出文件夹"""
        dir_path = QFileDialog.getExistingDirectory(
            self, "选择输出文件夹", str(get_script_dir())
        )
        if dir_path:
            self.outputlineEdit_2.setText(dir_path)

    def start_processing(self):
        """开始处理文件"""
        
        # 读取“是否保留原文件”开关状态
        keep_original = self.SwitchButton.isChecked()
        
        wechat_path = self.wechatlineEdit_2.text().strip()
        output_path = self.outputlineEdit_2.text().strip()

        # 验证路径
        if not wechat_path:
            QMessageBox.warning(self, "警告", "请选择微信文件夹路径")
            return

        # 禁用按钮防止重复点击
        self.Start_2.setEnabled(False)
        self.Cancel_2.setEnabled(True)
        self.progressBar.setValue(0)
        self.LogTextBrowser.clear()

        # 创建并启动处理线程
        self.processing_thread = FileProcessingThread(wechat_path, output_path, keep_original)
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
        self.LogTextBrowser.moveCursor(self.LogTextBrowser.textCursor().End)

    def on_process_finished(self):
        """处理完成回调"""
        self.Start_2.setEnabled(True)
        self.Cancel_2.setEnabled(False)
        self.processing_thread = None

    def closeEvent(self, event):
        """窗口关闭时确保线程终止"""
        if self.processing_thread and self.processing_thread.isRunning():
            self.processing_thread.stop()
            self.processing_thread.wait()
        event.accept()

if __name__ == "__main__":
    # 确保中文显示正常
    font = QtGui.QFont("微软雅黑")
    app = QApplication(sys.argv)
    app.setFont(font)
    
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())