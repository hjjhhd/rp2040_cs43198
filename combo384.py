import time
from machine import Pin


FN_PINS = [1, 2, 3, 8]


class Combo384():
    def __init__(self, PINS = FN_PINS):
        self.rate = (32000, 44100, 48000, 88200, 96000, 176400, 192000, 352800, 384000)
        self.fn_pin = [Pin(n, Pin.IN, Pin.PULL_UP) for n in PINS]

    def Fn():
        fn = 0


        return fn