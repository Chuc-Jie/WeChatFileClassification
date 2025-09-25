#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
软件名称：微信文件分类剪切器（多线程 + 自定义输出目录 + 同名智能重命名）
功能    ：把微信 PC 端"在文件夹中显示"得到的月份目录里所有文件，
          按扩展名自动分类剪切到 用户指定\Files\<后缀>\ 下。
          可选择是否按文件修改日期进行二次分类。
版本    ：1.4.0
作者    ：友野
"""

from pathlib import Path
import sys
import shutil
import datetime
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import re

# -------------------- 通用函数 --------------------
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
        print(f'[ERROR] {"复制" if copy_only else "移动"}失败：{src_path} -> {target}  {e}')

# -------------------- 主流程 --------------------
def main() -> None:
    # 让用户输入微信文件夹路径（包含月份文件夹的目录）
    folder_path = input('请输入微信文件夹路径（包含月份文件夹的目录）：').strip()
    file_dir = Path(folder_path)
    
    if not file_dir.is_dir():
        print('| 路径无效，程序退出')
        sys.exit(1)

    # 扫描月份文件夹 (格式: YYYY-MM)
    month_dirs = [p for p in file_dir.iterdir() 
                 if p.is_dir() and re.match(r'\d{4}-\d{2}', p.name)]
    print(f'| 发现 {len(month_dirs)} 个月份文件夹: {[d.name for d in month_dirs]}')

    # 按文件类型分类
    files_by_type = defaultdict(list)
    for month_folder in month_dirs:
        print(f'| 扫描文件夹: {month_folder.name}')
        for file_path in month_folder.rglob('*'):
            if file_path.is_file():
                # 处理文件后缀
                suffix = file_path.suffix.lower()
                if suffix:  # 有后缀名
                    suffix = suffix[1:]  # 去掉点号
                else:  # 无后缀名
                    suffix = 'no_ext'
                files_by_type[suffix].append(str(file_path.resolve()))

    # 计算总文件数
    total_files = sum(len(v) for v in files_by_type.values())
    print(f'| 总计 {len(files_by_type)} 个文件类型，{total_files} 个文件')

    # 让用户决定 Files 文件夹的输出根目录
    custom_root = input('请设置 Files 文件夹的输出路径（直接回车=脚本目录）：').strip()
    if custom_root:
        out_root = Path(custom_root).resolve()
    else:
        out_root = get_script_dir()
    print(f'| 输出根目录：{out_root}')

    # 让用户选择是否按日期进行二次分类
    date_choice = input('是否按文件修改日期进行二次分类？(y/n)：').strip().lower()
    use_date_category = date_choice.startswith('y')
    print(f'| 日期二次分类：{"启用" if use_date_category else "禁用"}')

    # 让用户选择是否保留原文件
    keep_choice = input('是否保留原文件（复制而非移动）？(y/n)：').strip().lower()
    keep_original = keep_choice.startswith('y')
    print(f'| 保留原文件：{"是" if keep_original else "否"}')

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
            # 根据选择决定是否添加日期子目录（二级分类）
            if use_date_category:
                try:
                    # 获取文件修改时间
                    mtime = src_path.stat().st_mtime
                    date_str = datetime.datetime.fromtimestamp(mtime).strftime('%Y-%m-%d')
                    date_dir = type_dir / date_str  # 二级目录：Files/<后缀>/YYYY-MM-DD
                    date_dir.mkdir(parents=True, exist_ok=True)
                    dst = date_dir / src_path.name
                except Exception as e:
                    print(f'[警告] 无法获取文件 {src} 的日期信息，将直接保存到类型目录：{e}')
                    dst = type_dir / src_path.name
            else:
                # 不按日期分类，直接保存到类型目录
                dst = type_dir / src_path.name
            tasks.append((src, dst, keep_original))

    if not tasks:
        print('| 未找到可处理的文件')
        return

    # 执行多线程处理
    print(f'| 开始处理 {len(tasks)} 个文件...')
    WORKERS = min(32, len(tasks))
    completed = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = [pool.submit(move_file, src, dst, copy_only) for src, dst, copy_only in tasks]
        for fut in as_completed(futures):
            completed += 1
            # 每完成 100 个或最后一个任务时打印进度
            if completed % 100 == 0 or completed == len(tasks):
                print(f'| 已完成 {completed}/{len(tasks)}')
            # 获取任务结果（捕获异常用）
            try:
                fut.result()
            except Exception as e:
                print(f'[错误] {e}')

    # 全部任务完成提示
    print('| 全部操作完成！')

# -------------------- 入口 --------------------
if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\n| 用户中断，程序退出')
    except Exception as e:
        print(f'\n| 程序出错: {e}')