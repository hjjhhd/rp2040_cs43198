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
# 按当前硬件约定，DSD模式使用外部MCLK直通，标称频率固定为22.5792 MHz。
DSD_MCLK_HZ = 22_579_200

rled_pin = Pin(RLED_PIN, Pin.OUT, value=0)
gled_pin = Pin(GLED_PIN, Pin.OUT, value=0)
pcm_pin = Pin(PCMCH_PIN, Pin.IN)
bal_pin = Pin(BALCH_PIN, Pin.IN)
dsdon_pin = Pin(DSDON_PIN, Pin.IN)
# Combo384新版接口表将排针16脚定义为S/PDIF RX ENABLE；播放速率改由F0-F3读取。
plug_pin = Pin(PLUG_PIN, Pin.IN)
balch_out_pin = Pin(BALCH_OUT_PIN, Pin.OUT, value=0)
sech_out_pin = Pin(SECH_OUT_PIN, Pin.OUT, value=0)
hw_mute_pin = Pin(HW_MUTE_PIN, Pin.OUT, value=1)    # 与hw_mute一致：1为静音，启动创建GPIO时立即建立硬件静音。
mute_in_pin = Pin(MUTE_PIN, Pin.IN)     # 修正Combo384静音输入脚的Pin构造参数，避免启动时报AttributeError。
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
        cs43198.I2C1_SCL_PIN, cs43198.I2C1_SDA_PIN, DSDON_PIN, PLUG_PIN, PCMCH_PIN, BALCH_PIN,
        BALCH_OUT_PIN, SECH_OUT_PIN, HW_MUTE_PIN
        )
Gpio_in = (mute_in_pin, pcm_pin, bal_pin, dsdon_pin, plug_pin, detbal_l_pin, detbal_r_pin, detse_l_pin, detse_r_pin,
           Ctrl.fn_pin[0], Ctrl.fn_pin[1], Ctrl.fn_pin[2], Ctrl.fn_pin[3])  # 修正为访问Combo384实例的输入引脚列表。
Pending = False
Dac_Interrupt_Pending = False
Last_irq_ms = 0  # 新增软件去抖时间戳，记录最近一次被接受的GPIO中断时间。
IRQ_DEBOUNCE_MS = 50  # 新增去抖窗口，过滤机械开关和耳机触点的重复边沿。
# DAC数字静音后等待软斜坡衰减，再切断继电器；恢复时等待继电器触点稳定后再解除DAC静音。
# 按已确认方案等待150ms；规格书4.2.1软斜坡约1dB/ms，原50ms不足以覆盖全量程静音衰减。
DAC_MUTE_SETTLE_MS = 150
RELAY_SETTLE_MS = 50



def interrupt(pin=None):  # 修改为接收Pin.irq传入的引脚参数；本回调暂不读取该参数。
    global Pending, Last_irq_ms  # 修正中断回调的作用域，使回调能够修改主循环读取的Pending。
    now_ms = time.ticks_ms()  # 新增读取MicroPython单调毫秒计时器，用于软件去抖。
    # 修正跨引脚事件丢失：每个边沿均标记待处理，机械去抖由_detect的稳定快照完成。
    Pending = True
    Last_irq_ms = now_ms

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
    # 采样率变化复用完整的静音、掉电、时钟切换和继电器恢复顺序，避免此入口提前解除DAC静音。
    detect()

def initialization():
    # 启动入口捕获I2C异常和掉电超时：立即断开硬件输出，禁止异常后继续解除静音。
    try:
        _initialization()
    except Exception:
        hw_mute(True)
        raise


def _initialization():
    # 复位前无法依赖数字静音，因此先建立硬件静音，再复位两片共用RESET的DAC。
    global L_ID, R_ID
    hw_mute(True)
    Left.reset()
    L_ID = None
    R_ID = None
    # 器件ID校验保留有限重试，持续失败由外层异常保护保持继电器断开。
    for attempt in range(10):
        try:
            L_ID = Left.read_device_id()
            R_ID = Right.read_device_id()
            if L_ID == (0x43, 0x19, 0x80) and R_ID == (0x43, 0x19, 0x80):
                break
        except OSError:
            pass
        time.sleep_ms(3)
    else:
        raise RuntimeError("CS43198 器件 ID 校验失败：左={}，右={}".format(L_ID, R_ID))

    # 复位后保留默认RCO与接口/模拟输出掉电状态；先建立数字静音并配置模拟参数。
    for dac in (Left, Right):
        dac.mute_pcm(True)
        dac.set_dsd_mute(True)
        dac.set_dsd_enabled(False)
        dac.configure_class_h()
        dac.configure_analog_output()
    # 启动与运行切换共用同一套消抖、原始编码校验和MUTE检查，避免无效格式仍启动ASP或HP。
    detect()
    # 完成初始化后启用输入双边沿中断，并安排复查，覆盖启用中断前短窗口内的状态变化。
    for gpio in Gpio_in:
        gpio.irq(handler=interrupt, trigger=Pin.IRQ_RISING | Pin.IRQ_FALLING)
    int_pin.irq(handler=dac_interrupt, trigger=Pin.IRQ_FALLING)
    # 开放GPIO中断前INT可能已经拉低，主动补查，避免仅检测下降沿遗漏既有故障。
    if int_pin.value() == 0:
        dac_interrupt()
    global Pending  # 初始化末尾主动复查不经过中断去抖，避免短窗口事件遗漏。
    Pending = True


def detect():
    # 所有播放切换异常均优先硬件静音；重新抛出错误用于定位，不允许接着执行恢复播放。
    try:
        _detect()
    except Exception:
        hw_mute(True)
        raise


def _detect():
    global Pending  # 检测期间输入仍有变化时，重新置位供主循环再次处理。
    global Dac_Interrupt_Pending  # 正常重配置屏蔽故障源后丢弃旧中断请求，防止重复重启。
    # 正常切换先静音两片DAC并等待数字斜坡结束，再断开继电器，降低触点切换时的输出阶跃。
    dacs = (Left, Right)
    for dac in dacs:
        dac.configure_playback_interrupts(None)  # 先屏蔽两片故障源，掉电和切换时不产生误中断。
    Dac_Interrupt_Pending = False
    for dac in dacs:
        dac.mute_pcm(True)
        dac.set_dsd_mute(True)
    time.sleep_ms(DAC_MUTE_SETTLE_MS)
    hw_mute(True)

    # 等待机械触点稳定；两次读取全部输入不一致时保持静音，留给下一轮重新检测。
    first = tuple(gpio.value() for gpio in Gpio_in)
    first_irq_ms = Last_irq_ms  # 记录窗口起点；MUTE短脉冲结束后电平虽恢复，中断时间戳仍能发现切换。
    time.sleep_ms(IRQ_DEBOUNCE_MS)
    state = tuple(gpio.value() for gpio in Gpio_in)
    if state != first or Last_irq_ms != first_irq_ms:
        Pending = True
        return

    pcmch, balance, dsdon, plug = state[1:5]
    bal_l, bal_r, se_l, se_r = state[5:9]
    format_valid = (pcmch ^ dsdon) == 1
    is_dsd = bool(dsdon)
    output_ready = bool(plug and ((balance and bal_l and bal_r) or
                                  (not balance and se_l and se_r)))

    # 先关闭模拟输出并等待PDN_DONE，再关闭旧音频接口；任何失败都保持硬件静音。
    for dac in dacs:
        power = dac.power_down_playback()
        dac.power_down_control(power | 0xE0)
        dac.set_mclk_source("rco", 22_579_200)
    time.sleep_us(150)

    # 没有确定格式或USB未连接时停在RCO和DAC掉电状态，避免无效时钟进入播放路径。
    if not format_valid or not plug or state[0]:  # Combo384的MUTE=1时禁止启动接口和模拟输出。
        return

    # 新版图表PCM编码为0至8，DSD编码为9至12；先校验原始编码，禁止格式之间混用。
    rate_code = sum(value << bit for bit, value in enumerate(state[9:13]))
    # 新版规格书的DSD编码为9至12；用驱动Dsd_rate()解码，按CS43198处理器模式接纳64/128/256，拒绝板卡可报告但DAC不支持的512。
    if not is_dsd and rate_code > 8:
        return
    dsd_rate = None
    if is_dsd:
        try:
            dsd_rate = Ctrl.Dsd_rate(state[9:13])  # 使用已稳定的F0-F3快照，避免重复读取引脚。
        except ValueError:
            return
        if dsd_rate not in cs43198_reg.DSD_RATE_CODES:  # 与驱动的DSD_SPEED有效编码表保持一致。
            return
        # 驱动再次读F脚时若发生变化，保持静音并安排下一次稳定状态检测。
        if tuple(gpio.value() for gpio in Gpio_in) != state:
            Pending = True
            return
        # DSD时钟采用已指定的固定频率；此处仅防止配置常量被改成不支持的频率。
        if DSD_MCLK_HZ not in (22_579_200, 24_576_000):
            return

    # 修改为从同一份已消抖快照计算PCM编码、采样率和MCLK，避免采样期间的引脚变化混用新旧模式。
    # PCM采样率只在PCM路径使用；DSD倍速由Dsd_rate()从F0-F3专用编码得出。
    # DSD不再伪造384kHz的PCM采样率；USB PCM统一调用Combo384驱动解码同一份快照。
    sample_rate = None if is_dsd else Ctrl.rate[Ctrl.Fn(state[9:13])]
    mclk_hz = DSD_MCLK_HZ if is_dsd else Ctrl.Mclk_Hz_pcm(state[9:13])
    for dac in dacs:
        if is_dsd:
            dac.configure_dsd_mono(dsd_rate)
            dac.set_dsd_enabled(False)
        else:
            dac.configure_i2s_mono(sample_rate, word_length=32, role="slave")
            # 新增PCM切换时关闭DSD处理器，防止旧DSD_EN状态残留。
            dac.set_dsd_enabled(False)
        dac.set_mclk_source("direct", mclk_hz)
    time.sleep_us(150)

    # 模式继电器在硬件静音下先断后通；耳机未就绪时仍保持硬件静音。
    if output_ready:
        hw_mode("balance" if balance else "single_end")

    # 按规格书防爆音顺序启用新接口、DSD处理器和DAC模拟输出。
    for dac in dacs:
        dac.configure_popguard(True)
        power = dac.read_reg(cs43198_reg.REG_POWER_DOWN)
        power &= 0xDF if is_dsd else 0xBF
        dac.power_down_control(power)
        if is_dsd:
            dac.set_dsd_enabled(True)
        dac.power_down_control(power & 0xEF)
    time.sleep_ms(12)
    for dac in dacs:
        dac.configure_popguard(False)
        # 按规格书4.11在模块启动后清除粘滞状态，避免后续开放中断时把启动事件误当新故障。
        # 下一步再读取持续故障；不能仅清除状态就认为接口已经正常。
        dac.clear_interrupt_status()

    mode = "dsd" if is_dsd else "pcm"
    # 启动事件清除后再次读取；任一片仍有当前路径故障均保持静音，等待输入变化后重试。
    faults = tuple(dac.playback_fault_present(mode) for dac in dacs)
    if any(faults):
        return

    # 重新确认全部输入未变；变化或输出未就绪时保持静音并安排下一轮检测。
    if tuple(gpio.value() for gpio in Gpio_in) != state or Last_irq_ms != first_irq_ms:
        Pending = True
        return
    if not output_ready:
        return
    for dac in dacs:
        dac.configure_playback_interrupts(mode)  # 只在正常播放前开放当前路径故障，PDN_DONE继续轮询。
    # 开放屏蔽位可能立即拉低INT；不能在已知故障待处理时接通继电器。
    if Dac_Interrupt_Pending or int_pin.value() == 0:
        dac_interrupt()
        return
    # DAC仍保持数字静音；先接通硬件静音继电器并等待触点稳定，再检查输入并放行声音。
    hw_mute(False)
    time.sleep_ms(RELAY_SETTLE_MS)
    if (tuple(gpio.value() for gpio in Gpio_in) != state or
            Last_irq_ms != first_irq_ms or  # MUTE或模式脚在配置期间出现过短脉冲时，重新稳定检测后再放行。
            Dac_Interrupt_Pending or int_pin.value() == 0):  # 继电器稳定期间新出现的故障也禁止数字解除静音。
        hw_mute(True)
        Pending = True
        return
    for dac in dacs:
        if is_dsd:
            dac.set_dsd_mute(False)
        else:
            dac.mute_pcm(False)

def dac_detect():
    # DAC中断处理先执行最低爆音风险的数字静音，再等待软斜坡衰减后断开硬件继电器。
    dacs = (Left, Right)
    try:
        for dac in dacs:
            dac.configure_playback_interrupts(None)  # 检查和恢复期间先屏蔽故障源，避免同一故障重复触发。
        for dac in dacs:
            dac.mute_pcm(True)
            dac.set_dsd_mute(True)
        time.sleep_ms(DAC_MUTE_SETTLE_MS)
        hw_mute(True)

        # 调试和状态读取必须分别走左右DAC对象，禁止混用I2C总线；错误处理由dac_debug封装。
        left_errors = Left.dac_debug()
        right_errors = Right.dac_debug()
        # 保存本次两侧结果，供后续普通detect或主循环诊断使用；不把左右错误混在一起。
        global Dac_debug_errors_l, Dac_debug_errors_r
        Dac_debug_errors_l = left_errors
        Dac_debug_errors_r = right_errors

        # 修正驱动将通信异常转换为字符串后被忽略的问题；任一侧读状态失败均禁止恢复播放。
        if "i2c_error" in left_errors or "i2c_error" in right_errors:
            raise RuntimeError("CS43198 中断状态读取失败，保持硬件静音")

        # 按要求交给普通detect完成重新读取输入、重新配置DAC以及最终解除静音。
        detect()
    except Exception:
        # 调试或普通检测任一步失败时，保持硬件静音，避免异常状态下恢复输出。
        hw_mute(True)
        raise

if __name__ == "__main__":
    # 初始化或检测流程发生异常时锁存红灯；只有正常进入并持续运行主循环才点亮绿灯。
    dac_logic_error = False
    try:
        initialization()
        gled_pin.value(1)  # 初始化成功且主循环可以正常运行，点亮绿灯。
        rled_pin.value(0)  # 正常状态关闭红灯。
    except Exception:
        gled_pin.value(0)  # 初始化失败时关闭绿灯。
        rled_pin.value(1)  # 初始化失败时点亮红灯。
        dac_logic_error = True

    while True:
        try:
            if Dac_Interrupt_Pending:
                Dac_Interrupt_Pending = False
                dac_detect()
            elif Pending:
                # 故障中断优先于普通引脚变化，避免普通重配置清掉尚未诊断的故障请求。
                Pending = False
                detect()
            if not dac_logic_error:
                gled_pin.value(1)  # 本轮逻辑正常完成，保持绿灯。
                rled_pin.value(0)  # 本轮逻辑正常完成，关闭红灯。
        except Exception:
            # initialization、detect或dac_detect报错时锁存红灯，避免异常状态显示为正常。
            gled_pin.value(0)
            rled_pin.value(1)
            dac_logic_error = True
            hw_mute(True)  # 出错后保持硬件静音，防止异常状态继续输出声音。
