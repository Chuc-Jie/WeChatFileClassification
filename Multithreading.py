#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
软件名称：微信文件分类剪切器（多线程 + 自定义输出目录 + 同名智能重命名）
功能    ：把微信 PC 端“在文件夹中显示”得到的月份目录里所有文件，
          按扩展名自动分类剪切到 用户指定\Files\<后缀>\ 下。
          若目标重名，则在文件名后插入“_原父级文件夹名”。
版本    ：1.3.0
作者    ：友野
"""

from pathlib import Path
import sys
import shutil
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

# -------------------- 通用函数 --------------------
def get_script_dir() -> Path:
    """获取脚本（或打包后 exe）所在目录"""
    # 如果当前进程是 PyInstaller 打包后的可执行文件
    if getattr(sys, 'frozen', False):
        # 返回 exe 所在的父目录
        return Path(sys.executable).parent
    # 否则返回当前源码文件所在的目录
    return Path(__file__).parent.resolve()

def move_one(src: str, dst: Path, copy_only: bool = False) -> None:
    """
    移动单文件，重名处理：
    1. 目标已存在 → 在文件名后插入“_原父级文件夹名”
    2. 若仍冲突 → 继续加序号 (1)、(2)...
    """
    # 把字符串路径转成 Path 对象
    src_path = Path(src)
    # 取出源文件所在文件夹的名字，例如 2024-12
    parent_dir_name = src_path.parent.name
    # 分离目标文件的主文件名与扩展名
    stem, suffix = dst.stem, dst.suffix

    # 构造第一次重命名后的文件名：Bypass_2024-12.exe
    new_name = f"{stem}_{parent_dir_name}{suffix}"
    # 生成最终要写入的完整路径
    target = dst.with_name(new_name)

    # 如果目标已存在，则继续加序号直到不冲突
    counter = 1
    while target.exists():
        # 生成带序号的新名字，例如 Bypass_2024-12(1).exe
        target = dst.with_name(f"{stem}_{parent_dir_name}({counter}){suffix}")
        # 序号递增
        counter += 1

    # 真正执行文件移动
    try:
        if copy_only:
            # 复制文件（保留原文件）
            shutil.copy2(str(src_path), str(target))  # copy2保留元数据
        else:
            # 移动文件（剪切）
            shutil.move(str(src_path), str(target))
    except Exception as e:
        print(f'[ERROR] {"复制" if copy_only else "移动"}失败：{src_path} -> {target}  {e}')

# -------------------- 主流程 --------------------
def main() -> None:
    # 让用户输入“在微信中打开所在文件夹”后得到的路径（如 2025-06）
    folder_path = input('请输入“在微信中打开所在文件夹”后得到的路径（如 2025-06）：').strip()
    # 取输入路径的父目录作为后续扫描的根目录
    file_dir = Path(folder_path).parent
    # 如果该目录不存在，则提示并退出
    if not file_dir.is_dir():
        print('| 路径无效，程序退出')
        # 非正常退出
        sys.exit(1)

    # 列出根目录下所有子目录（即各个月份文件夹）
    sub_dirs = [p for p in file_dir.iterdir() if p.is_dir()]
    # 打印统计到的月份文件夹数量
    print(f'| 总计 {len(sub_dirs)} 个月份文件夹')

    # 用于按后缀归类文件：key=后缀，value=文件绝对路径字符串列表
    files_by_type = defaultdict(list)
    # 遍历每个月份文件夹
    for folder in sub_dirs:
        # 递归遍历该文件夹下所有层级的文件
        for file in folder.rglob('*'):
            # 只处理文件，跳过目录
            if file.is_file():
                # 取出扩展名并去掉前导点，转成小写；若无扩展名则用 'no_ext'
                suffix = file.suffix.lstrip('.').lower() or 'no_ext'
                # 把文件绝对路径字符串加入对应后缀的列表
                files_by_type[suffix].append(str(file.resolve()))

    # 计算总文件数
    total_files = sum(len(v) for v in files_by_type.values())
    # 打印文件类型数与总文件数
    print(f'| 总计 {len(files_by_type)} 个文件类型，{total_files} 个文件')

    # 让用户决定 Files 文件夹的输出根目录
    custom_root = input('请设置 Files 文件夹的输出路径（直接回车=脚本目录）：').strip()
    # 如果用户输入了路径，则解析成绝对路径
    if custom_root:
        out_root = Path(custom_root).resolve()
    # 否则使用脚本所在目录
    else:
        out_root = get_script_dir()
    # 打印最终使用的输出根目录
    print(f'| 输出根目录：{out_root}')

    # 用于保存“后缀 -> 对应目标文件夹 Path”的映射
    type_dir_map = {}
    # 为每个后缀创建 Files\<后缀> 目录
    for suf in files_by_type.keys():
        # 构造目标目录路径，例如 D:\Output\Files\pdf
        target = out_root / 'Files' / suf
        # 确保目录存在（parents=True 自动创建多级）
        target.mkdir(parents=True, exist_ok=True)
        # 记录映射关系
        type_dir_map[suf] = target

    # 组装多线程任务列表：每个元素是 (源文件绝对路径字符串, 目标完整路径 Path)
    tasks = []
    # 遍历每个后缀及其文件列表
    for suf, file_list in files_by_type.items():
        # 取出该后缀对应的目标根目录
        root = type_dir_map[suf]
        # 为每个文件生成一个任务元组
        tasks.extend([(src, root / Path(src).name) for src in file_list])

    # 打印待执行任务总数
    print(f'| 开始多线程剪切（任务数：{len(tasks)}）……')
    # 设置线程池大小
    WORKERS = 32
    # 创建线程池
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        # 提交所有移动任务，返回 Future 列表
        futures = [pool.submit(move_one, src, dst) for src, dst in tasks]
        # 逐个等待任务完成
        for idx, fut in enumerate(as_completed(futures), 1):
            # 每完成 500 个或最后一个任务时打印进度
            if idx % 500 == 0 or idx == len(tasks):
                print(f'  已完成 {idx}/{len(tasks)}')
            # 获取任务结果（捕获异常用）
            fut.result()

    # 全部任务完成提示
    print('| 全部剪切完成！')

# -------------------- 入口 --------------------
if __name__ == '__main__':
    try:
        # 进入主函数
        main()
    # 用户按下 Ctrl+C 时优雅退出
    except KeyboardInterrupt:
        print('\n| 用户中断，程序退出')