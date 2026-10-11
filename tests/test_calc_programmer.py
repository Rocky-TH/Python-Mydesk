# -*- coding: utf-8 -*-
"""计算器程序员模式测试

1. 位宽调整：字节(8)/字(16)/双字(32)/四字(64)，结果按位宽截断，
   二进制/十六进制补齐显示
2. 十进制有符号（补码）/无符号两种转换方式
3. 运算溢出回绕、取负、有符号除法语义
"""
import sys
import os

sys.path.insert(0, '.')
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

results = []

def check(name, condition, detail=''):
    status = 'PASS' if condition else 'FAIL'
    results.append((name, status, detail))
    print(f'[{status}] {name}' + (f' — {detail}' if detail else ''))


from PyQt6.QtWidgets import QApplication

from plugins.calc_tool.calc_tool_widget import CalcToolWidget

app = QApplication.instance() or QApplication(sys.argv)
w = CalcToolWidget({'name': 'calc'})
w.resize(900, 600)
w.show()
w.calc_mode_combo.setCurrentIndex(1)  # 程序员模式（触发 reset）

# ===== 1. UI 控件 =====
check('1.1 位宽下拉存在且默认双字(32位)',
      w.prog_width_combo.currentText() == "双字 (32位)"
      and w._prog_bit_width == 32)
check('1.2 位宽选项完整（字节/字/双字/四字）',
      [w.prog_width_combo.itemText(i) for i in range(4)] ==
      ["字节 (8位)", "字 (16位)", "双字 (32位)", "四字 (64位)"])
check('1.3 符号方式默认无符号',
      w.prog_sign_combo.currentText() == "无符号" and w._prog_signed is False)


def type_number(num):
    for ch in str(num):
        w._on_calc_input(ch)


def dec():
    return w.prog_dec_value.text()


def binn():
    return w.prog_bin_value.text()


def hexx():
    return w.prog_hex_value.text()


# ===== 2. 字节宽度：255 显示与补齐 =====
w.prog_width_combo.setCurrentIndex(0)  # 字节 8 位
type_number(255)
check('2.1 字节无符号 255 十进制显示', dec() == '255', dec())
check('2.2 字节 255 二进制补齐 8 位（每4位分组）',
      binn() == '0b 1111 1111', binn())
check('2.3 字节 255 十六进制 FF（2位补齐）',
      hexx() == '0x FF', hexx())

# ===== 3. 溢出截断：256 → 0；300 → 44 =====
w._on_calc_clear()
type_number(256)
check('3.1 字节位宽 256 溢出截断为 0', dec() == '0', dec())
w._on_calc_clear()
type_number(300)
check('3.2 字节位宽 300 截断为 44', dec() == '44', dec())
check('3.3 截断值 44 的十六进制 0x 2C', hexx() == '0x 2C', hexx())

# ===== 4. 有符号补码转换 =====
w._on_calc_clear()
type_number(255)
w.prog_sign_combo.setCurrentIndex(1)  # 有符号
check('4.1 字节 255 有符号 = -1', dec() == '-1', dec())
check('4.2 主显示同步为 -1', w.calc_display.text() == '-1')
check('4.3 有符号时二进制/十六进制仍为补码位型 FF',
      binn() == '0b 1111 1111' and hexx() == '0x FF')

w._on_calc_clear()
type_number(128)
check('4.4 字节 128 有符号 = -128', dec() == '-128', dec())

w._on_calc_clear()
type_number(127)
check('4.5 字节 127 有符号仍为 127', dec() == '127', dec())

# 切回无符号恢复
w._on_calc_clear()
type_number(255)
w.prog_sign_combo.setCurrentIndex(1)
w.prog_sign_combo.setCurrentIndex(0)
check('4.6 有符号→无符号往返：-1 恢复 255', dec() == '255', dec())

# ===== 5. 切换位宽即时截断当前值 =====
w.prog_width_combo.setCurrentIndex(2)  # 双字
w._on_calc_clear()
type_number(300)
check('5.1 双字下 300 不截断', dec() == '300', dec())
w.prog_width_combo.setCurrentIndex(0)  # 切字节
check('5.2 双字 300 切字节后截断为 44', dec() == '44' and w.calc_display.text() == '44')

# ===== 6. 运算溢出回绕（字节无符号 250 + 10 = 4） =====
w.prog_width_combo.setCurrentIndex(0)
w.prog_sign_combo.setCurrentIndex(0)
w._on_calc_clear()
type_number(250)
w._on_calc_operator('+')
type_number(10)
w._on_calc_equals()
check('6.1 字节无符号 250+10 溢出回绕 = 4', dec() == '4' and w.calc_display.text() == '4',
      f"dec={dec()}")
check('6.2 回绕结果十六进制 0x 04', hexx() == '0x 04')

# ===== 7. 有符号运算：字节 -56 / 2 = -28 =====
w._on_calc_clear()
# 无符号下输入 200，切有符号显示 -56；以 -56 作为操作数参与除法
type_number(200)
w.prog_sign_combo.setCurrentIndex(1)
check('7.1 200 的有符号解释为 -56', dec() == '-56', dec())
w._on_calc_operator('/')
type_number(2)
w._on_calc_equals()
check('7.2 字节有符号 -56/2 = -28', dec() == '-28' and w.calc_display.text() == '-28',
      f"dec={dec()}")
check('7.3 -28 的补码十六进制为 E4', hexx() == '0x E4', hexx())

# ===== 8. 取负：字节 1 取负 = -1（补码 FF），切无符号=255 =====
w.prog_width_combo.setCurrentIndex(0)
w.prog_sign_combo.setCurrentIndex(1)
w._on_calc_clear()
type_number(1)
w._on_calc_negate()
check('8.1 字节有符号 1 取负 = -1', dec() == '-1', dec())
check('8.2 -1 补码位型 FF', hexx() == '0x FF')
w.prog_sign_combo.setCurrentIndex(0)
check('8.3 切无符号后 = 255', dec() == '255', dec())

# ===== 9. 字/双字/四字 补齐位数 =====
w.prog_sign_combo.setCurrentIndex(0)
w.prog_width_combo.setCurrentIndex(1)  # 字
w._on_calc_clear()
type_number(1)
check('9.1 字宽 1 二进制补齐 16 位',
      binn() == '0b 0000 0000 0000 0001', binn())
check('9.2 字宽 1 十六进制补齐 4 位（按字节分组）',
      hexx() == '0x 00 01', hexx())

w.prog_width_combo.setCurrentIndex(3)  # 四字
w._on_calc_clear()
type_number(1)
check('9.3 四字宽 1 二进制补齐 64 位',
      binn() == '0b ' + '0000 ' * 15 + '0001', binn()[:12])
check('9.4 四字宽 1 十六进制补齐 16 位',
      hexx() == '0x ' + '00 ' * 7 + '01', hexx()[:14])

# ===== 10. 双字默认下普通转换不受影响 =====
w.prog_width_combo.setCurrentIndex(2)
w._on_calc_clear()
type_number(65535)
check('10.1 双字 65535 = 0x 00 00 FF FF', hexx() == '0x 00 00 FF FF', hexx())

# ===== 11. 标准模式不被位宽逻辑影响 =====
w.calc_mode_combo.setCurrentIndex(0)
w._on_calc_clear()
w.calc_display.setText("7")
w._on_calc_operator('+')
w.calc_display.setText("8")
w._on_calc_equals()
check('11.1 标准模式 7+8=15（浮点/普通路径不受影响）',
      w.calc_display.text() == '15', w.calc_display.text())

w.deleteLater()

print('\n========== 汇总 ==========')
failed = [r for r in results if r[1] == 'FAIL']
print(f'总计 {len(results)} 项，通过 {len(results) - len(failed)} 项，失败 {len(failed)} 项')
for name, status, detail in failed:
    print(f'  FAIL: {name} {detail}')
sys.exit(1 if failed else 0)
