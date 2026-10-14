import time
from machine import Pin


FN_PINS = (1, 2, 3, 8)


class Combo384():
    def __init__(self, PINS = FN_PINS):
        self.rate = (32000, 44100, 48000, 88200, 96000, 176400, 192000, 352800, 384000)
        self.fn_pin = [Pin(n, Pin.IN) for n in PINS]  # 修改为SDK示例形式，省略不必要的None上拉参数。

    def Fn(self):
        fn = 0
        if len(self.fn_pin) == 4:
            fn = min(8,self.fn_pin[0].value() + self.fn_pin[1].value() * 2 + self.fn_pin[2].value() * 4 + self.fn_pin[3].value() * 8)
        return fn

    def Mclk_Hz_pcm(self):
        return 24_576_000 if not self.fn_pin[0].value() else 22_579_200

    def Dsd_rate(self):
        # 新版Combo384规格书规定F3..F0的1001、1010、1011、1100分别表示DSD64、128、256、512。
        if len(self.fn_pin) == 4:
            fn_dsd = self.fn_pin[0].value() + self.fn_pin[1].value() * 2 + self.fn_pin[2].value() * 4 + self.fn_pin[3].value() * 8
            if fn_dsd == 9:
                return 64
            elif fn_dsd == 10:
                return 128
            elif fn_dsd == 11:
                return 256
            elif fn_dsd == 12:
                return 512
            else:
                raise ValueError("Fn格式错误")
        # 引脚数量不正确时明确报错，避免调用方把隐式None当作有效DSD速率。
        raise ValueError("DSD频率检测需要4个F引脚")
