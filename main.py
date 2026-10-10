import combo384
import cs43198_reg
import cs43198


MUTE_PIN = 22

Ctrl = combo384.Combo384()
Left = cs43198.CS43198_L()
Right = cs43198.CS43198_R()
Pins = (combo384.FN_PINS[0], combo384.FN_PINS[1], combo384.FN_PINS[2], combo384.FN_PINS[3],
        MUTE_PIN        
        )
global Pending
Pending = False


def interrupt():
    Pending = True

def pcm_setrate():
    Left.mute_pcm()
    Right.mute_pcm()
    Left.set_sample_rate(Ctrl.rate[Ctrl.Fn()])
    Right.set_sample_rate(Ctrl.rate[Ctrl.Fn()])
    Left.set_mclk_source("direct", Ctrl.Mclk_Hz())
    Right.set_mclk_source("direct", Ctrl.Mclk_Hz())
    Left.mute_pcm(False)
    Right.mute_pcm(False)



def detect():
    pass


if __name__ == "__main__":
    while True:
        pass