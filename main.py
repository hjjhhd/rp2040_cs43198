import combo384
import cs43198_reg
import cs43198
import time
from machine import I2C, Pin



MUTE_PIN = 22
RLED_PIN = 15
GLED_PIN = 14
DSDON_PIN = 9
PCMCH_PIN = 27
BALCH_PIN = 28

rled_pin = Pin(RLED_PIN, Pin.OUT, value=0)
gled_pin = Pin(GLED_PIN, Pin.OUT, value=0)
pcm_pin = Pin(PCMCH_PIN, Pin.IN)
bal_pin = Pin(BALCH_PIN, Pin.IN)

Ctrl = combo384.Combo384()
Left = cs43198.CS43198_L()
Right = cs43198.CS43198_R()
Pins = (combo384.FN_PINS[0], combo384.FN_PINS[1], combo384.FN_PINS[2], combo384.FN_PINS[3],
        MUTE_PIN, RLED_PIN, GLED_PIN, cs43198.RESET_PIN, cs43198.I2C0_SCL_PIN, cs43198.I2C0_SDA_PIN,
        cs43198.I2C1_SCL_PIN, cs43198.I2C1_SDA_PIN     
        )
global Pending
Pending = False
global L_ID
global R_ID


def interrupt():
    Pending = True


def pcm_setrate():
    Left.mute_pcm()
    Right.mute_pcm()
    Left.set_mclk_source("direct", Ctrl.Mclk_Hz())
    Right.set_mclk_source("direct", Ctrl.Mclk_Hz())
    Left.configure_i2s_mono(Ctrl.rate[Ctrl.Fn()])
    Right.configure_i2s_mono(Ctrl.rate[Ctrl.Fn()])
    Left.mute_pcm(False)
    Right.mute_pcm(False)

def initialization():
    Left.reset()
    while (L_ID == None or R_ID == None):
        L_ID = Left.read_device_id()
        R_ID = Right.read_device_id()
    Left.set_mclk_source("direct", Ctrl.Mclk_Hz())
    Right.set_mclk_source("direct", Ctrl.Mclk_Hz())
    if DSDON_PIN == 1:
        pass
    else:
        Left.configure_i2s_mono(Ctrl.rate[Ctrl.Fn()])
        Right.configure_i2s_mono(Ctrl.rate[Ctrl.Fn()])
        Left.mute_pcm()
        Right.mute_pcm()
    
def detect():
    pass


if __name__ == "__main__":
    initialization()
    while True:
        pass