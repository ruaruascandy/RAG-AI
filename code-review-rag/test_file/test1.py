# test1.py – 包含空指针、资源未关闭、逻辑错误等典型问题

import os

def risky_function(data):
    """可能引发空指针异常的函数"""
    # 缺陷1: 未检查data是否为None
    return data.upper()  

def file_processor(filename):
    """未正确关闭文件资源"""
    # 缺陷2: 文件打开后未关闭
    f = open(filename, 'r')
    content = f.read()
    # 缺陷3: 未处理文件不存在的异常
    return content

def infinite_loop_risk(n):
    """可能导致无限循环的逻辑错误"""
    result = 0
    # 缺陷4: while循环条件可能永远为真 (n为负数时)
    while n > 0:
        result += n
        n -= 1
    return result

def unused_parameter(a, b, c):
    """存在未使用的参数"""
    # 缺陷5: 参数b和c未被使用
    return a * 2

# 缺陷6: 全局变量命名不规范
GlobalVar = 100

if __name__ == "__main__":
    # 测试调用
    print(risky_function(None))          # 会抛出 AttributeError
    print(file_processor("not_exist.txt"))  # 会抛出 FileNotFoundError
    print(infinite_loop_risk(-5))        # 逻辑错误：应返回0但循环条件判断失误