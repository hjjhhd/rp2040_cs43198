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
DETSE_L_PIN = 16
DETSE_R_PIN = 17
INT_PIN = 0

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
int_pin = Pin(INT_PIN, Pin.IN)

Ctrl = combo384.Combo384()
Left = cs43198.CS43198_L()
Right = cs43198.CS43198_R()
Pin_numbers = (combo384.FN_PINS[0], combo384.FN_PINS[1], combo384.FN_PINS[2], combo384.FN_PINS[3],
        MUTE_PIN, RLED_PIN, GLED_PIN, cs43198.RESET_PIN, cs43198.I2C0_SCL_PIN, cs43198.I2C0_SDA_PIN,
        cs43198.I2C1_SCL_PIN, cs43198.I2C1_SDA_PIN, DSDON_PIN, DSD_PIN, PLUG_PIN, PCMCH_PIN, BALCH_PIN,
        BALCH_OUT_PIN, SECH_OUT_PIN, HW_MUTE_PIN
        )
Gpio_in = (pcm_pin, bal_pin, dsdon_pin, dsd_pin, plug_pin, detbal_l_pin, detbal_r_pin, detse_l_pin, detse_r_pin,
           Ctrl.fn_pin[0], Ctrl.fn_pin[1], Ctrl.fn_pin[2], Ctrl.fn_pin[3])  # 修正为访问Combo384实例的输入引脚列表。
Pending = False
Dac_Interrupt_Pending = False
Last_irq_ms = 0  # 新增软件去抖时间戳，记录最近一次被接受的GPIO中断时间。
IRQ_DEBOUNCE_MS = 50  # 新增去抖窗口，过滤机械开关和耳机触点的重复边沿。



def interrupt(pin=None):  # 修改为接收Pin.irq传入的引脚参数；本回调暂不读取该参数。
    global Pending, Last_irq_ms  # 修正中断回调的作用域，使回调能够修改主循环读取的Pending。
    now_ms = time.ticks_ms()  # 新增读取MicroPython单调毫秒计时器，用于软件去抖。
    if time.ticks_diff(now_ms, Last_irq_ms) >= IRQ_DEBOUNCE_MS:  # 新增去抖判断，窗口内边沿不重复触发。
        Pending = True  # 保留中断只置位标志，不在中断上下文执行detect或I2C操作。
        Last_irq_ms = now_ms  # 新增记录本次已接受的中断时间。

def dac_interrupt(pin=None):  # 修正Pin.irq回调签名，接收触发中断的引脚对象。
    global Dac_Interrupt_Pending
    Dac_Interrupt_Pending = True

def hw_mute(mute = True):
    hw_mute_pin.value(1 if mute else 0)
    time.sleep_ms(20)  # 修正延时单位：MicroPython的sleep参数为秒，这里需要20毫秒继电器稳定时间。
    if mute:
        balch_out_pin.value(0)
        sech_out_pin.value(0)

def hw_mode(mode):
    # 新增先校验模式，错误参数不应改变现有继电器状态。
    if mode not in ("balance", "single_end"):
        raise ValueError("mode 必须为 balance 或 single_end")
    # 新增切换前强制硬件静音，避免直接调用hw_mode时继电器切换产生爆音。
    hw_mute_pin.value(1)
    time.sleep_ms(20)  # 新增继电器切换前的静音建立时间。
    # 新增先断后通，避免由单端切到平衡时两组继电器短暂同时接通。
    balch_out_pin.value(0)
    sech_out_pin.value(0)
    time.sleep_ms(20)  # 新增等待旧触点释放，再接通目标输出。
    balch_out_pin.value(1 if mode == "balance" else 0)
    sech_out_pin.value(1 if mode == "single_end" else 0)
    time.sleep_ms(20)  # 新增继电器动作后的稳定时间；函数返回时仍保持硬件静音。

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
    hw_mute(True)  # 新增复位前建立硬件静音，遮蔽复位和后续DAC上电瞬态。
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
    output_ready = False  # 新增默认未就绪状态，避免无有效格式时引用未赋值变量。
    # 新增初始化阶段先建立硬件静音，后续所有继电器模式切换均在静音状态下进行。
    hw_mute(True)
    if bal_pin.value() == 1:
        hw_mode("balance")  # 新增根据当前输出选择设置平衡继电器模式。
    else:
        hw_mode("single_end")  # 新增根据当前输出选择设置单端继电器模式。
    if not format_valid:
        for dac in dacs:
            # 新增无有效音频流时主动保持PCM和DSD路径静音，避免启动时输出未定义数据。
            dac.mute_pcm(True)  # 修改为调用驱动封装，保持 PCM 路径静音。
            dac.set_dsd_mute(True)  # 修改为调用驱动封装，保持 DSD 路径静音。
            hw_mute(True)  # 新增对应硬件静音，确保无效格式时继电器也保持断开。
    elif is_dsd:
        for dac in dacs:
            # 新增读取Combo384第16脚DSD64_128状态：低为DSD64，高为DSD128。
            dsd_rate = 128 if dsd_pin.value() else 64
            dac.configure_dsd_mono(dsd_rate)  # 修改为按板卡倍速状态配置，只使用CS43198支持的64/128。
            # 新增清除提前设置的 DSD_EN，确保后续先启动 DSDIF，再启用 DSD 处理。
            dac.set_dsd_enabled(False)  # 修改为调用驱动封装，先关闭 DSD_EN 再上电 DSDIF。
            # 新增 DSD 软斜坡、双通道音量联动和自动静音；上电期间保持手动静音。
            dac.set_dsd_mute(True)  # 修改为调用驱动封装，DSD 配置期间保持静音。
            hw_mute(True)  # 新增对应硬件静音，确保DSD配置期间不会经过继电器输出。
    else:
        # 修改PCM初始化：使用驱动配置采样率、字长、I2S从机和单声道；主从机模式下这些是必要项。
        for dac in dacs:
            dac.configure_i2s_mono(sample_rate, word_length=32, role="slave")
            # 删除对主机模式分频寄存器的写入：CS43198此处为从机，分频输出参数不参与时钟生成。
            # 新增 PCM 软斜坡、双通道音量联动及自动静音；初始化结束前保持数字静音。
            dac.mute_pcm(True)  # 修改为调用驱动封装，PCM 配置期间保持静音。
            hw_mute(True)  # 新增对应硬件静音，确保PCM配置期间不会经过继电器输出。

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
            hw_mute(True)  # 新增对应硬件静音，等待后续检测函数确认有效音源。
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

    # 新增最终硬件解除静音：只有软件路径已满足输出检测条件时才释放继电器静音。
    if format_valid and output_ready:
        # 新增恢复被hw_mute(True)断开的输出继电器；模式切换期间仍保持硬件静音。
        hw_mode("balance" if bal_pin.value() == 1 else "single_end")
        hw_mute(False)
    else:
        hw_mute(True)

    # 新增初始化完成后统一开启所有输入GPIO的双边沿中断，避免配置期间触发无效事件。
    for gpio in Gpio_in:
        gpio.irq(handler=interrupt, trigger=Pin.IRQ_RISING | Pin.IRQ_FALLING)
    int_pin.irq(handler=dac_interrupt, trigger=Pin.IRQ_FALLING)
    
def detect():
    pass

def dac_detect():
    pass

if __name__ == "__main__":
    initialization()
    while True:
        if Pending:
            Pending = False  # 新增在轮询取走事件后清除标志，允许下一次中断再次触发detect。
            detect()
        if Dac_Interrupt_Pending:
            Dac_Interrupt_Pending = False
            dac_detect()
