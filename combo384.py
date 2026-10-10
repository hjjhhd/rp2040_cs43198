import time
from machine import Pin


FN_PINS = (1, 2, 3, 8)


class Combo384():
    def __init__(self, PINS = FN_PINS):
        self.rate = (32000, 44100, 48000, 88200, 96000, 176400, 192000, 352800, 384000)
        self.fn_pin = [Pin(n, Pin.IN, None) for n in PINS]

    def Fn(self):
        fn = 0
        if len(self.fn_pin) == 4:
            fn = min(7,self.fn_pin[0] + self.fn_pin[1] * 2 + self.fn_pin[2] * 4 + self.fn_pin[3] * 8 - 1)
        return fn

    def Mclk_Hz(self):
        return 24_576_000 if self.fn_pin[0] else 22_579_200

