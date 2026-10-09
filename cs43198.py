"""RP2040 MicroPython 双总线控制 CS43198 的基础驱动。"""

import time
from machine import I2C, Pin

import cs43198_reg as reg


# ======================== 引脚占位定义 ========================
# 注意：以下引脚均按要求先设为 GP1。实际使用前务必修改，避免 SCL、SDA、RESET
# 相互冲突或不属于对应 I2C 外设。I2C0 常见配对为 SDA=GP0/SCL=GP1 或
# SDA=GP4/SCL=GP5；I2C1 常见配对为 SDA=GP2/SCL=GP3、GP6/GP7 等。
I2C0_SCL_PIN = 1  # 提醒：占位 GP1，须按接线修改
I2C0_SDA_PIN = 1  # 提醒：占位 GP1，须按接线修改，不能与 SCL 同脚
I2C1_SCL_PIN = 1  # 提醒：占位 GP1，须按接线修改为 I2C1 可用引脚
I2C1_SDA_PIN = 1  # 提醒：占位 GP1，须按接线修改，不能与 SCL 同脚
RESET_PIN = 1     # 提醒：占位 GP1；两颗 DAC 共用此复位脚，拉低会同时复位


class _CS43198Base:
    """封装 CS43198 的 24 位寄存器 I2C 访问和通用播放控制。"""

    def __init__(self, bus_id, scl_pin, sda_pin, i2c=None, address=reg.I2C_ADDRESS,
                 freq=reg.I2C_FREQ_HZ, reset_pin=RESET_PIN, side="left"):
        """创建一颗 DAC 的驱动对象；引脚仍为占位值，初始化不执行播放配置。

        i2c 可传入预先创建的 machine.I2C；否则按 bus_id、SCL、SDA 创建硬件总线。
        RESET 两颗芯片共用，构造时只将其释放为高电平，不会执行复位脉冲。
        """
        self.address = address
        self.side = side
        self.bus_id = bus_id
        self.scl_pin = scl_pin
        self.sda_pin = sda_pin
        self.i2c = i2c if i2c is not None else I2C(
            bus_id,
            scl=Pin(scl_pin),
            sda=Pin(sda_pin),
            freq=freq,
        )
        self.reset_pin = Pin(reset_pin, Pin.OUT, value=1) if reset_pin is not None else None

    def write_reg(self, address, value):
        """向一个 24 位 MAP 地址写入一个 8 位寄存器值；超范围参数会报错。

        CS43198 控制字节的 SIZE=00 表示 8 位寄存器访问。调用前须确保芯片已脱离
        RESET 且复位释放后等待规格书要求的上电时间。
        """
        if not 0 <= address <= 0xFFFFFF:
            raise ValueError("寄存器地址必须是 24 位")
        if not 0 <= value <= 0xFF:
            raise ValueError("寄存器值必须是 8 位")
        payload = bytes((
            (address >> 16) & 0xFF,
            (address >> 8) & 0xFF,
            address & 0xFF,
            reg.I2C_CONTROL_BYTE,
            value,
        ))
        self.i2c.writeto(self.address, payload)

    def read_reg(self, address):
        """读取一个 24 位 MAP 地址的 8 位寄存器值；读取状态寄存器可能清除中断。

        先发送 3 字节寄存器地址和 8 位控制字节，再以重复起始条件读取数据。
        对有读清除行为的寄存器，读取结果本身会改变芯片状态。
        """
        if not 0 <= address <= 0xFFFFFF:
            raise ValueError("寄存器地址必须是 24 位")
        pointer = bytes((
            (address >> 16) & 0xFF,
            (address >> 8) & 0xFF,
            address & 0xFF,
            reg.I2C_CONTROL_BYTE,
        ))
        self.i2c.writeto(self.address, pointer, stop=False)
        return self.i2c.readfrom(self.address, 1)[0]

    def write_regs(self, address, values):
        """从指定 24 位地址连续写入多个 8 位寄存器；仅适合地址连续的寄存器段。

        CS43198 的 INCR 位设为 1。请勿跨越保留区或使用该方法写入地址不连续的
        系数表；规格书要求保留位保持默认值。
        """
        if not 0 <= address <= 0xFFFFFF:
            raise ValueError("寄存器地址必须是 24 位")
        data = bytes(values)
        if not data:
            return
        payload = bytes((
            (address >> 16) & 0xFF,
            (address >> 8) & 0xFF,
            address & 0xFF,
            reg.I2C_CONTROL_BYTE_INCREMENT,
        )) + data
        self.i2c.writeto(self.address, payload)

    def reset(self, low_ms=2, settle_ms=2):
        """通过共用 RESET GPIO 产生硬件复位脉冲；会同时复位左右两颗 CS43198。

        复位释放后至少等待芯片完成上电和 ADR 地址锁存，再调用其他寄存器方法；
        默认等待时间按规格书的 1.5 ms 上电示例留有余量。
        """
        if self.reset_pin is None:
            raise RuntimeError("创建对象时未配置 reset_pin")
        self.reset_pin.value(0)
        time.sleep_ms(low_ms)
        self.reset_pin.value(1)
        time.sleep_ms(settle_ms)

    def read_device_id(self):
        """读取只读器件 ID 的三个字节；可用于确认 I2C 地址和通信是否正常。"""
        return (
            self.read_reg(reg.REG_DEVICE_ID_A_B),
            self.read_reg(reg.REG_DEVICE_ID_C_D),
            self.read_reg(reg.REG_DEVICE_ID_E),
        )

    def set_sample_rate(self, sample_rate):
        """设置 ASP PCM 采样率；可用值见寄存器表中的 32 kHz 至 384 kHz 标准档。

        该设置需与 Combo384 输出的 LRCK 及 MCLK_INT 匹配；384 kHz 主模式要求
        MCLK_INT 为 24.576 MHz。函数不会自动改动 MCLK 源或 Combo384 的模式脚。
        """
        try:
            code = reg.SAMPLE_RATE_CODES[sample_rate]
        except KeyError:
            raise ValueError("不支持的 PCM 采样率: {}".format(sample_rate))
        self.write_reg(reg.REG_SERIAL_SAMPLE_RATE, code)

    def set_pcm_word_length(self, bits):
        """设置 ASP 有效采样字长为 8、16、24 或 32 位；与 I2S 时隙宽度分别配置。

        只更新 ASP_SPSIZE 字段，XSP_SPSIZE 保持规格书默认值 01（24 位）。
        """
        try:
            code = reg.PCM_WORD_LENGTH_CODES[bits]
        except KeyError:
            raise ValueError("PCM 字长仅支持 8、16、24 或 32 位")
        self.write_reg(reg.REG_SERIAL_SAMPLE_SIZE, 0x04 | code)

    def set_mclk_source(self, source, internal_mclk_hz):
        """设置内部 MCLK 源及其标称频率；PLL 模式须先完成 PLL 参数与启动。

        source 可为 direct、pll 或 rco；internal_mclk_hz 仅支持 22.5792 MHz 或
        24.576 MHz。调用时需确认外部时钟和 Combo384 工作模式与设置相符。
        """
        sources = {"direct": 0x00, "pll": 0x01, "rco": 0x02}
        if source not in sources:
            raise ValueError("source 必须为 direct、pll 或 rco")
        if internal_mclk_hz == 22_579_200:
            rate_bit = 0x04
        elif internal_mclk_hz == 24_576_000:
            rate_bit = 0x00
        else:
            raise ValueError("MCLK_INT 仅支持 22.5792 MHz 或 24.576 MHz")
        self.write_reg(reg.REG_SYSTEM_CLOCKING, rate_bit | sources[source])

    def configure_i2s_mono(self, sample_rate=44100, word_length=32, role="slave"):
        """设置 I2S 输入为单声道时隙，并应用 CS43198 的 PCM 单声道滤波系数。

        左芯片选 I2S 左时隙、右芯片选右时隙；role 默认 slave，适用于 Combo384
        输出 BCLK/LRCK 的常见连接。须由主控确保字长、时钟极性、MCLK 与实际信号吻合。
        本方法只配置 ASP/PCM，不启动振荡器、PLL、DAC 输出或 Combo384 模式脚。
        """
        if role not in ("slave", "master"):
            raise ValueError("role 必须为 slave 或 master")
        self.set_sample_rate(sample_rate)
        self.set_pcm_word_length(word_length)
        # I2S 帧格式：ASP_STP=0、ASP_5050=1、ASP_FSD=010。
        self.write_reg(reg.REG_ASP_FRAME_CONFIG, 0x0A)
        # I2S 时钟极性使用规格书示例值；主从位按调用方选择。
        self.write_reg(reg.REG_ASP_CLOCK_CONFIG, 0x0C | (0x10 if role == "master" else 0))
        # 单声道输入时两个通道选择相同时隙；左/右由 active phase 区分。
        phase = 0x08 if self.side == "right" else 0x00
        self.write_reg(reg.REG_ASP_CHANNEL_1_LOCATION, 0x00)
        self.write_reg(reg.REG_ASP_CHANNEL_2_LOCATION, 0x00)
        # I2S 示例使用 32 位数据；有效位字长由 ASP_SPSIZE 单独设置。
        self.write_reg(reg.REG_ASP_CHANNEL_1_SIZE_ENABLE, phase | 0x07)
        self.write_reg(reg.REG_ASP_CHANNEL_2_SIZE_ENABLE, phase | 0x07)
        self.write_reg(reg.REG_PCM_FILTER_OPTION, 0x02)
        self.write_reg(reg.REG_PCM_VOLUME_A, 0x00)
        self.write_reg(reg.REG_PCM_VOLUME_B, 0x00)
        for address, value in reg.PCM_MONO_FILTER_ENABLE:
            self.write_reg(address, value)

    def set_pcm_volume(self, volume, channel="both"):
        """设置 PCM 音量寄存器；音量编码应按规格书 PCM_VOLUME 的 dB/步进规则传入。

        volume 必须是 8 位寄存器码 0x00–0xFF（0xFF 为数字静音）；both 同时写 A/B，
        A 或 B 只写单路。
        """
        if not 0 <= volume <= 0xFF:
            raise ValueError("PCM 音量码必须在 0x00–0xFF 范围内")
        if channel in ("both", "A"):
            self.write_reg(reg.REG_PCM_VOLUME_A, volume)
        if channel in ("both", "B"):
            self.write_reg(reg.REG_PCM_VOLUME_B, volume)
        if channel not in ("both", "A", "B"):
            raise ValueError("channel 必须为 both、A 或 B")

    def mute_pcm(self, mute=True):
        """设置 PCM A/B 软静音位；取消静音前请确认时钟和有效音频数据已稳定。"""
        value = self.read_reg(reg.REG_PCM_PATH_CONTROL_1)
        value = (value | 0x03) if mute else (value & 0xFC)
        self.write_reg(reg.REG_PCM_PATH_CONTROL_1, value)

    def configure_dsd_mono(self, rate=64):
        """配置 DSD 处理器路径为单声道；rate 支持 64、128 或 256 倍速。

        Combo384 必须同时输出与此设置匹配的 DSD 数据和 DSDCLK。两片均从本芯片
        DSD 接口取流；左右片应用规格书示例中的通道选择/复制/反相配置。
        此方法配置规格书 mono 示例中的 DSD 处理器模式，不配置 Direct DSD 路径；
        函数也不自动切换 MCLK、启动 DAC 或设置 Combo384。
        """
        try:
            speed = reg.DSD_RATE_CODES[rate]
        except KeyError:
            raise ValueError("DSD 速率仅支持 64、128 或 256")
        self.write_reg(reg.REG_DSD_INTERFACE_CONFIG, 0x00)  # DSD 时钟从模式
        self.write_reg(reg.REG_DSD_VOLUME_A, 0x00)
        self.write_reg(reg.REG_DSD_VOLUME_B, 0x00)
        # DSD_EN=1，静态/无效 DSD 检测开启，DSD_PRC_SRC=00 选择专用 DSDIF。
        value = 0x10 | (speed << 2) | 0x03
        self.write_reg(reg.REG_DSD_PATH_CONTROL_2, value)
        # 左片用 C5，右片用 C7：规格书 mono DSD 示例的 channel A/B 组合。
        self.write_reg(reg.REG_DSD_PATH_CONTROL_3, 0xC7 if self.side == "right" else 0xC5)

    def set_dsd_volume(self, volume, channel="both"):
        """设置 DSD 音量寄存器；volume 为 8 位寄存器码，具体 dB 映射按规格书表查用。

        DSD 与 PCM 的参考电平设置不同；混合播放时还需遵守 MIX_PCM_PREP/MIX_PCM_DSD 顺序。
        """
        if not 0 <= volume <= 0xFF:
            raise ValueError("DSD 音量码必须是 8 位")
        if channel in ("both", "A"):
            self.write_reg(reg.REG_DSD_VOLUME_A, volume)
        if channel in ("both", "B"):
            self.write_reg(reg.REG_DSD_VOLUME_B, volume)
        if channel not in ("both", "A", "B"):
            raise ValueError("channel 必须为 both、A 或 B")

    def power_down_control(self, value):
        """直接写入 0x020000 电源控制寄存器；调用者须按规格书维持保留位为 0。

        各 PDN 位为 1 表示对应模块掉电；错误顺序可能导致爆音或时钟/数据通路异常。
        """
        self.write_reg(reg.REG_POWER_DOWN, value)


class CS43198_L(_CS43198Base):
    """左声道 CS43198：默认使用 I2C0，I2S/DSD 单声道输入选左时隙。"""

    def __init__(self, i2c=None, scl_pin=I2C0_SCL_PIN, sda_pin=I2C0_SDA_PIN,
                 address=reg.I2C_ADDRESS, freq=reg.I2C_FREQ_HZ, reset_pin=RESET_PIN):
        """创建左 DAC 对象；修改默认占位 GPIO 后再使用，或传入已初始化 I2C0。

        ADDR 接地时两片地址相同，因使用独立 I2C 总线所以可以共用 0x30。
        """
        super().__init__(0, scl_pin, sda_pin, i2c, address, freq, reset_pin, "left")


class CS43198_R(_CS43198Base):
    """右声道 CS43198：默认使用 I2C1，I2S/DSD 单声道输入选右时隙。"""

    def __init__(self, i2c=None, scl_pin=I2C1_SCL_PIN, sda_pin=I2C1_SDA_PIN,
                 address=reg.I2C_ADDRESS, freq=reg.I2C_FREQ_HZ, reset_pin=RESET_PIN):
        """创建右 DAC 对象；修改默认占位 GPIO 后再使用，或传入已初始化 I2C1。

        左右对象的 reset() 操作共用 RESET 引脚，因此每次硬件复位会同时复位两片。
        """
        super().__init__(1, scl_pin, sda_pin, i2c, address, freq, reset_pin, "right")
