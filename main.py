import combo384
import cs43198_reg
import cs43198


Ctrl = combo384.Combo384()
Left = cs43198.CS43198_L()
Right = cs43198.CS43198_R()
Pins = (1, 2, 3, 8)
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


if __name__ == "__main__":
    pass