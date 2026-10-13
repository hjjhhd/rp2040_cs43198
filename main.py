import combo384
import cs43198_reg
import cs43198
import time
from machine import I2C, Pin



MUTE_PIN = 20
RLED_PIN = 15
GLED_PIN = 14
DSDON_PIN = 9
DSD_PIN = 21
PLUG_PIN = 22
PCMCH_PIN = 27
BALCH_PIN = 28
BALCH_OUT_PIN = 18
SECH_OUT_PIN = 19
HW_MUTE_PIN = 11
DETBAL_L_PIN = 12
DETBAL_R_PIN = 13
DETSE_L_PIN = 162
DETSE_R_PIN = 17

rled_pin = Pin(RLED_PIN, Pin.OUT, value=0)
gled_pin = Pin(GLED_PIN, Pin.OUT, value=0)
pcm_pin = Pin(PCMCH_PIN, Pin.IN)
bal_pin = Pin(BALCH_PIN, Pin.IN)
dsdon_pin = Pin(DSDON_PIN, Pin.IN)
dsd_pin = Pin(DSD_PIN, Pin.IN)
plug_pin = Pin(PLUG_PIN, Pin.IN)
balch_out_pin = Pin(BALCH_OUT_PIN, Pin.OUT, value=0)
sech_out_pin = Pin(SECH_OUT_PIN, Pin.OUT, value=0)
hw_mute_pin = Pin(HW_MUTE_PIN, Pin.OUT, value=0)    #值为0时静音，值为1时取消静音
detbal_l_pin = Pin(DETBAL_L_PIN, Pin.IN)
detbal_r_pin = Pin(DETBAL_R_PIN, Pin.IN)
detse_l_pin = Pin(DETSE_L_PIN, Pin.IN)
detse_r_pin = Pin(DETSE_R_PIN, Pin.IN)

Ctrl = combo384.Combo384()
Left = cs43198.CS43198_L()
Right = cs43198.CS43198_R()
Pin_numbers = (combo384.FN_PINS[0], combo384.FN_PINS[1], combo384.FN_PINS[2], combo384.FN_PINS[3],
        MUTE_PIN, RLED_PIN, GLED_PIN, cs43198.RESET_PIN, cs43198.I2C0_SCL_PIN, cs43198.I2C0_SDA_PIN,
        cs43198.I2C1_SCL_PIN, cs43198.I2C1_SDA_PIN, DSDON_PIN, DSD_PIN, PLUG_PIN, PCMCH_PIN, BALCH_PIN,
        BALCH_OUT_PIN, SECH_OUT_PIN, HW_MUTE_PIN
        )
global Pending
Pending = False



def interrupt():
    Pending = True

def hw_mute():
    hw_mute_pin.value(1)

def pcm_setrate():
    Left.mute_pcm()
    Right.mute_pcm()
    Left.set_mclk_source("direct", Ctrl.Mclk_Hz())
    Right.set_mclk_source("direct", Ctrl.Mclk_Hz())
    Left.configure_i2s_mono(Ctrl.rate[Ctrl.Fn()])
    Right.configure_i2s_mono(Ctrl.rate[Ctrl.Fn()])
    Left.mute_pcm(False)
    Right.mute_pcm(False)

def initialization():  # 修改为一次性启动初始化；持续监测和格式切换由主循环/检测函数负责。
    # 新增函数内全局声明和初值，替代原先未初始化变量的无限等待循环。
    global L_ID, R_ID
    L_ID = None
    R_ID = None
    dacs = (Left, Right)  # 新增统一对象列表，保证左右两片执行相同的上电步骤。
    Left.reset()  # 保留共用复位调用；驱动内部已有复位后的 3 ms 等待。
    # 修改 ID 检测：验证完整器件 ID，并对 I2C 异常进行最多十次重试。
    for attempt in range(10):
        try:
            L_ID = Left.read_device_id()
            R_ID = Right.read_device_id()
            if L_ID == (0x43, 0x19, 0x80) and R_ID == (0x43, 0x19, 0x80):
                break
        except OSError:
            pass  # 新增有限重试处理；持续失败时由循环结束后的异常报告。
        time.sleep_ms(3)  # 新增重试间隔，避免连续访问尚未就绪的控制口。
    else:
        raise RuntimeError("CS43198 器件 ID 校验失败：左={}，右={}".format(L_ID, R_ID))

    # 修改为按项目约定读取一次当前时钟和采样率，避免左右芯片取得不同配置快照。
    # 外部 MCLK 必须已稳定且持续存在；软件延时无法证明外部时钟实际有效。
    mclk_hz = Ctrl.Mclk_Hz()
    sample_rate = Ctrl.rate[Ctrl.Fn()]
    for dac in dacs:
        dac.set_mclk_source("direct", mclk_hz)
    time.sleep_us(150)  # 新增规格书要求的时钟源切换等待，之后才访问音频配置。

    # 修改为PCMCH与DSDON异或确认格式；00/11均代表无效或冲突，必须保持静音。
    pcmch_state = pcm_pin.value()
    dsdon_state = dsdon_pin.value()
    format_valid = pcmch_state ^ dsdon_state
    is_dsd = bool(dsdon_state) if format_valid else False
    if not format_valid:
        for dac in dacs:
            # 新增无有效音频流时主动保持PCM和DSD路径静音，避免启动时输出未定义数据。
            dac.mute_pcm(True)  # 修改为调用驱动封装，保持 PCM 路径静音。
            dac.set_dsd_mute(True)  # 修改为调用驱动封装，保持 DSD 路径静音。
    elif is_dsd:
        for dac in dacs:
            # 新增读取Combo384第16脚DSD64_128状态：低为DSD64，高为DSD128。
            dsd_rate = 128 if dsd_pin.value() else 64
            dac.configure_dsd_mono(dsd_rate)  # 修改为按板卡倍速状态配置，只使用CS43198支持的64/128。
            # 新增清除提前设置的 DSD_EN，确保后续先启动 DSDIF，再启用 DSD 处理。
            dac.set_dsd_enabled(False)  # 修改为调用驱动封装，先关闭 DSD_EN 再上电 DSDIF。
            # 新增 DSD 软斜坡、双通道音量联动和自动静音；上电期间保持手动静音。
            dac.set_dsd_mute(True)  # 修改为调用驱动封装，DSD 配置期间保持静音。
    else:
        # 修改PCM初始化：使用驱动配置采样率、字长、I2S从机和单声道；主从机模式下这些是必要项。
        for dac in dacs:
            dac.configure_i2s_mono(sample_rate, word_length=32, role="slave")
            # 删除对主机模式分频寄存器的写入：CS43198此处为从机，分频输出参数不参与时钟生成。
            # 新增 PCM 软斜坡、双通道音量联动及自动静音；初始化结束前保持数字静音。
            dac.mute_pcm(True)  # 修改为调用驱动封装，PCM 配置期间保持静音。

    for dac in dacs:
        # 新增明确的模拟输出设置：沿用规格书内部 VCPFILT、高电压模式的默认电源方案。
        # 该方案要求 VP 至少 3.3 V、负载至少 600 欧姆；输出满量程选规格书示例 1.732 Vrms。
        dac.configure_class_h()  # 修改为调用驱动封装，使用内部 VCPFILT 的 Class H 配置。
        dac.configure_analog_output()  # 修改为调用驱动封装，设置规格书示例输出满量程。
        # 新增读取状态以清除复位后的粘滞事件，不在这里启用未处理的外部中断。
        dac.read_reg(cs43198_reg.REG_INTERRUPT_STATUS_1)
        dac.read_reg(0x0F0004 if is_dsd else 0x0F0001)
        # 新增规格书例5-3/5-4的防爆音准备写入，必须先于接口及DAC上电。
        dac.configure_popguard(True)  # 修改为调用驱动封装，准备防爆音上电。
        # 新增接口上电：只清除当前播放接口的掉电位，其余电源位保持不变。
        power = dac.read_reg(cs43198_reg.REG_POWER_DOWN)
        power &= 0xDF if is_dsd else 0xBF
        dac.power_down_control(power)
        if is_dsd:
            # 新增在 DSDIF 上电后启用 DSD 处理，落实规格书第 4.9 节要求的顺序。
            dac.set_dsd_enabled(True)  # 修改为调用驱动封装，接口上电后再使能 DSD 处理器。
        dac.power_down_control(power & 0xEF)  # 新增最后清除 PDN_HP，启动模拟 DAC 输出。

    time.sleep_ms(12)  # 新增等待两片输出完成防爆音上电，之后再恢复临时寄存器。
    for dac in dacs:
        dac.configure_popguard(False)  # 修改为调用驱动封装，恢复防爆音临时寄存器默认值。
        if not format_valid:
            # 新增无有效格式时继续保持两条数字路径静音，等待后续检测函数确认模式。
            dac.mute_pcm(True)  # 修改为调用驱动封装，保持无流状态的 PCM 静音。
            dac.set_dsd_mute(True)  # 修改为调用驱动封装，保持无流状态的 DSD 静音。
        elif is_dsd:
            # 新增解除静音条件：必须已插入USB，且按平衡/单端模式确认对应左右检测均有效。
            output_ready = (plug_pin.value() == 1 and
                            ((bal_pin.value() == 1 and detbal_l_pin.value() == 1 and detbal_r_pin.value() == 1) or
                             (bal_pin.value() == 0 and detse_l_pin.value() == 1 and detse_r_pin.value() == 1)))
            if output_ready:
                # 新增 DSD 最终解除手动静音，保留软斜坡和自动静音设置。
                dac.set_dsd_mute(False)  # 修改为调用驱动封装，满足插入和输出检测后才解除静音。
            else:
                # 新增检测未就绪时继续保持 DSD 静音，避免无插入或输出检测异常时产生爆音。
                dac.set_dsd_mute(True)
        else:
            # 新增解除静音条件：必须已插入USB，且按平衡/单端模式确认对应左右检测均有效。
            output_ready = (plug_pin.value() == 1 and
                            ((bal_pin.value() == 1 and detbal_l_pin.value() == 1 and detbal_r_pin.value() == 1) or
                             (bal_pin.value() == 0 and detse_l_pin.value() == 1 and detse_r_pin.value() == 1)))
            if output_ready:
                # 修改原先无条件解除静音的逻辑，满足插入和输出检测后才允许PCM播放。
                dac.mute_pcm(False)
            else:
                # 新增检测未就绪时继续保持 PCM 静音，等待后续检测函数重新判断。
                dac.mute_pcm(True)
    
def detect():
    pass


if __name__ == "__main__":
    initialization()
    while True:
        if Pending == True:
            pass
