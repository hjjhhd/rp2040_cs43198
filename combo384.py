import time
from machine import Pin


FN_PINS = (1, 2, 3, 8)


class Combo384():
    def __init__(self, PINS = FN_PINS):
        self.rate = (32000, 44100, 48000, 88200, 96000, 176400, 192000, 352800, 384000)
        self.fn_pin = [Pin(n, Pin.IN) for n in PINS]  # 修改为SDK示例形式，省略不必要的None上拉参数。

    def _rate_code(self, values=None):
        # 新版图表按F3..F0编码；可传入主循环的稳定快照，避免格式和速率来自不同读取时刻。
        values = tuple(pin.value() for pin in self.fn_pin) if values is None else tuple(values)
        if len(values) != 4 or any(value not in (0, 1) for value in values):
            raise ValueError("采样率检测需要4个有效F引脚电平")
        return sum(value << bit for bit, value in enumerate(values))

    def Fn(self, values=None):
        # 新版规格书PCM只定义0至8；9至12为DSD，不能钳位成384kHz。
        code = self._rate_code(values)
        if code > 8:
            raise ValueError("无效PCM采样率编码")
        return code

    def Mclk_Hz_pcm(self, values=None):
        # 仅根据有效USB PCM编码选择时钟系列；图片未给出S/PDIF输出实际采样率，不能用于该模式。
        return 24_576_000 if not self.Fn(values) & 1 else 22_579_200

    def Dsd_rate(self, values=None):
        # 新版Combo384规格书规定F3..F0的1001、1010、1011、1100分别表示DSD64、128、256、512。
        if values is not None or len(self.fn_pin) == 4:
            fn_dsd = self._rate_code(values)  # 从同一份快照解码9/10/11/12，分别对应64/128/256/512。
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
