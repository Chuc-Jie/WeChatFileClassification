"""
软件名称：微信文件分类剪切器
功能    ：把微信 PC 端“在文件夹中显示”得到的月份目录里所有文件，
          按扩展名自动分类剪切到 脚本目录\Files\<后缀>\ 下。
版本    ：1.4.1
作者    ：友野
"""

from pathlib import Path
import sys
from os.path import dirname as opdirname
from os.path import abspath as opabspath
from os.path import join as opjoin
import shutil

# 示例路径：D:\minic\Documents\xwechat_files\wxid_wogvv1239spm22_9381\msg\file\2025-06

# 用户在微信里右键文件 →【在文件夹中显示】后拿到的路径示例
FolderPath = input("请输入路径：")

# 往上退一级，得到“file”目录，后面所有月份文件夹都在它里面
file_dir = Path(FolderPath).parent

# 所有子文件夹路径列表
sub_dirs = [p for p in file_dir.iterdir() if p.is_dir()]

print(f'| 总计 {len(sub_dirs)} 个文件夹')


from collections import defaultdict
# 用来存放结果的 dict：key → 后缀（不含点），value → 绝对路径列表
files_by_type = defaultdict(list)

for folder in sub_dirs:                # 之前已经拿到的 file/2025-06 这类目录
    for file in folder.rglob('*'):     # rglob 递归遍历，只要当前层用 glob('*')
        if file.is_file():             # 只处理文件，跳过子目录
            files_by_type[file.suffix.lstrip('.')].append(str(file.resolve()))   # 绝对路径

# 文件类型列表
Suffixs = list(files_by_type.keys())

# 文件类型数量
print(f'| 总计 {len(Suffixs)} 个文件类型')

# 获取脚本目录
# 通过此方法统一好输出路径
if getattr(sys, 'frozen', False):
    script_dir = opdirname(sys.executable)
else:
    script_dir = opdirname(opabspath(__file__))
    
# 创建一个字典：键是文件类型，值是文件类型文件夹的绝对路径
type_dir_map = {}   

# 遍历创建'文件类型'文件夹
for i in Suffixs:

    # 拼接路径
    NewDirt = opjoin(script_dir, 'Files', i)

    # 创建文件夹，中间目录自动一起建，目录已存在时不抛异常
    Path(NewDirt).mkdir(parents=True, exist_ok=True)
    
    # 写入字典
    type_dir_map[i] = NewDirt 

# 将对应类型的文件剪切到对应文件类型文件夹
# 逐后缀、逐文件处理
for suffix, file_list in files_by_type.items(): 
    
    # 取出之前建好的目标目录
    target_root = type_dir_map[suffix]
    
    for src in file_list:
        
        # 拼接目标文件完整路径
        dst = Path(target_root) / Path(src).name
        
        # 执行移动（剪切）
        shutil.move(src, dst)